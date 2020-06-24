import sqlite3
import pandas as pd
from pandas._testing import assert_frame_equal
import numpy as np
import os.path
from datetime import datetime, timedelta
import random
import pytest
from nempy import historical_spot_market_inputs as hi, markets, helper_functions as hf, \
    historical_interconnectors as hii, historical_unit_limits
from nempy import historical_inputs_from_xml as hist_xml
from time import time


# Define a set of random intervals to test
def get_test_intervals():
    start_time = datetime(year=2019, month=1, day=2, hour=0, minute=0)
    end_time = datetime(year=2019, month=2, day=1, hour=0, minute=0)
    difference = end_time - start_time
    difference_in_5_min_intervals = difference.days * 12 * 24
    random.seed(1)
    intervals = random.sample(range(1, difference_in_5_min_intervals), 100)
    times = [start_time + timedelta(minutes=5 * i) for i in intervals]
    times_formatted = [t.isoformat().replace('T', ' ').replace('-', '/') for t in times]
    return times_formatted


def test_setup():
    # Setup the database of historical inputs to test the Spot market class with.
    if not os.path.isfile('test_files/historical_inputs.db') or True:
        # Create a database for the require inputs.
        con = sqlite3.connect('test_files/historical_inputs.db')
        inputs_manager = hi.DBManager(connection=con)
        inputs_manager.DISPATCHINTERCONNECTORRES.create_table_in_sqlite_db()
        # Download data were inputs are needed on a monthly basis.
        finished = False
        for year in range(2019, 2020):
            for month in range(1, 2):
                if year == 2020 and month == 4:
                    finished = True
                    break
                inputs_manager.DISPATCHINTERCONNECTORRES.add_data(year=year, month=month)
                # inputs_manager.DISPATCHREGIONSUM.add_data(year=year, month=month)
                # inputs_manager.DISPATCHLOAD.add_data(year=year, month=month)
                # inputs_manager.BIDPEROFFER_D.add_data(year=year, month=month)
                # inputs_manager.BIDDAYOFFER_D.add_data(year=year, month=month)
                # inputs_manager.DISPATCHCONSTRAINT.add_data(year=year, month=month)
                # inputs_manager.DISPATCHPRICE.add_data(year=year, month=month)
                print(month)

            if finished:
                break

        # Download data where inputs are just needed from the latest month.
        # inputs_manager.INTERCONNECTOR.set_data(year=2020, month=3)
        # inputs_manager.LOSSFACTORMODEL.set_data(year=2020, month=3)
        # inputs_manager.LOSSMODEL.set_data(year=2020, month=3)
        # inputs_manager.DUDETAILSUMMARY.set_data(year=2020, month=3)
        # inputs_manager.DUDETAIL.create_table_in_sqlite_db()
        # inputs_manager.DUDETAIL.set_data(year=2020, month=3)
        # inputs_manager.INTERCONNECTORCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.GENCONDATA.set_data(year=2020, month=3)
        # inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.SPDREGIONCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.SPDINTERCONNECTORCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.INTERCONNECTOR.set_data(year=2020, month=3)  # Interconnector data
        # inputs_manager.MNSP_INTERCONNECTOR.set_data(year=2020, month=3)

        print('DB Build done.')
        con.close()


def test_historical_interconnector_losses():
    # Create a data base manager.
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        print(interval)
        INTERCONNECTOR = inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = inputs_manager.INTERCONNECTORCONSTRAINT.get_data(interval)
        interconnectors = hi.format_interconnector_definitions(INTERCONNECTOR, INTERCONNECTORCONSTRAINT)
        interconnector_loss_coefficients = hi.format_interconnector_loss_coefficients(INTERCONNECTORCONSTRAINT)
        LOSSFACTORMODEL = inputs_manager.LOSSFACTORMODEL.get_data(interval)
        interconnector_demand_coefficients = hi.format_interconnector_loss_demand_coefficient(LOSSFACTORMODEL)
        LOSSMODEL = inputs_manager.LOSSMODEL.get_data(interval)
        interpolation_break_points = hi.format_interpolation_break_points(LOSSMODEL)
        DISPATCHREGIONSUM = inputs_manager.DISPATCHREGIONSUM.get_data(interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)
        inter_flow = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)

        market = markets.Spot()

        inter_flow = inter_flow.loc[:, ['INTERCONNECTORID', 'MWFLOW', 'MWLOSSES']]
        inter_flow.columns = ['interconnector', 'MWFLOW', 'MWLOSSES']
        interconnectors = pd.merge(interconnectors, inter_flow, 'inner', on='interconnector')
        interconnectors['max'] = interconnectors['MWFLOW'] + 0.01
        interconnectors['min'] = interconnectors['MWFLOW'] - 0.01
        interconnectors = interconnectors.loc[:, ['interconnector', 'to_region', 'from_region', 'min', 'max']]
        market.set_interconnectors(interconnectors)

        # Create loss functions on per interconnector basis.
        loss_functions = hi.create_loss_functions(interconnector_loss_coefficients,
                                                  interconnector_demand_coefficients,
                                                  regional_demand.loc[:, ['region', 'loss_function_demand']])

        market.set_interconnector_losses(loss_functions, interpolation_break_points)

        # Calculate dispatch.
        market.dispatch()
        output = market.get_interconnector_flows()

        expected = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)
        expected = expected.loc[:, ['INTERCONNECTORID', 'MWFLOW', 'MWLOSSES']].sort_values('INTERCONNECTORID')
        expected.columns = ['interconnector', 'flow', 'losses']
        expected = expected.reset_index(drop=True)
        output = output.sort_values('interconnector').reset_index(drop=True)
        comparison = pd.merge(expected, output, 'inner', on='interconnector')
        comparison['diff'] = comparison['losses_x'] - comparison['losses_y']
        comparison['diff'] = comparison['diff'].abs()
        comparison['ok'] = comparison['diff'] < 0.5
        assert (comparison['ok'].all())


def test_using_availability_and_ramp_rates():
    """Test that using the availability and ramp up rate from DISPATCHLOAD always provides an upper bound on ouput.

    Note we only test for units in dispatch mode 0.0, i.e. not fast start units. Fast start units would appear to have
    their max output calculated using another procedure.
    """

    # Create a database for the require inputs.
    con = sqlite3.connect('test_files/historical_inputs.db')

    # Create a data base manager.
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval)
        dispatch_load = dispatch_load[dispatch_load['DISPATCHMODE'] == 0.0]
        dispatch_load = dispatch_load.loc[:, ['DUID', 'INITIALMW', 'AVAILABILITY', 'RAMPUPRATE', 'RAMPDOWNRATE',
                                              'TOTALCLEARED', 'DISPATCHMODE']]
        dispatch_load['RAMPMAX'] = dispatch_load['INITIALMW'] + dispatch_load['RAMPUPRATE'] * (5 / 60)
        dispatch_load['RAMPMIN'] = dispatch_load['INITIALMW'] - dispatch_load['RAMPDOWNRATE'] * (5 / 60)
        dispatch_load['assumption'] = ((dispatch_load['RAMPMAX'] + 0.01 >= dispatch_load['TOTALCLEARED']) &
                                       (dispatch_load['AVAILABILITY'] + 0.01 >= dispatch_load['TOTALCLEARED'])) | \
                                      (np.abs(dispatch_load['TOTALCLEARED'] - dispatch_load['RAMPMIN']) < 0.01)
        assert (dispatch_load['assumption'].all())


def test_max_capacity_not_less_than_availability():
    """For historical testing we are using availability as the unit capacity, so we want to test that the unit capacity
       or offer max is never lower than this value."""

    # Create a database for the require inputs.
    con = sqlite3.connect('test_files/historical_inputs.db')

    # Create a data base manager.
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval)
        dispatch_load = dispatch_load.loc[:, ['DUID', 'AVAILABILITY']]
        unit_capacity = inputs_manager.DUDETAIL.get_data(interval)
        unit_capacity = pd.merge(unit_capacity, dispatch_load, 'inner', on='DUID')
        unit_capacity['assumption'] = unit_capacity['AVAILABILITY'] <= unit_capacity['MAXCAPACITY']
        assert (unit_capacity['assumption'].all())


def test_determine_unit_limits():
    """Test the procedure for determining unit limits from historical inputs.

    It the limits set should always contain the historical amount dispatched within their bounds.
    """

    # Create a database for the require inputs.
    con = sqlite3.connect('test_files/historical_inputs.db')

    # Create a data base manager.
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval)
        dispatch_load = dispatch_load.loc[:, ['DUID', 'INITIALMW', 'AVAILABILITY', 'TOTALCLEARED', 'SEMIDISPATCHCAP',
                                              'RAMPUPRATE', 'RAMPDOWNRATE', 'DISPATCHMODE']]
        unit_capacity = inputs_manager.BIDPEROFFER_D.get_data(interval)
        unit_capacity = unit_capacity[unit_capacity['BIDTYPE'] == 'ENERGY']
        unit_limits = hi.determine_unit_limits(dispatch_load, unit_capacity)
        unit_limits = pd.merge(unit_limits, dispatch_load.loc[:, ['DUID', 'TOTALCLEARED', 'DISPATCHMODE']], 'inner',
                               left_on='unit', right_on='DUID')
        unit_limits['ramp_max'] = unit_limits['initial_output'] + unit_limits['ramp_up_rate'] * (5 / 60)
        unit_limits['ramp_min'] = unit_limits['initial_output'] - unit_limits['ramp_down_rate'] * (5 / 60)
        # Test the assumption that our calculated limits are not more restrictive then amount historically dispatched.
        unit_limits['assumption'] = ~((unit_limits['TOTALCLEARED'] > unit_limits['capacity'] + 0.01) |
                                      (unit_limits['TOTALCLEARED'] > unit_limits['ramp_max'] + 0.01) |
                                      (unit_limits['TOTALCLEARED'] < unit_limits['ramp_min'] - 0.01))
        assert (unit_limits['assumption'].all())


def test_if_schudeled_units_dispatched_above_bid_availability():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        print(interval)
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval).loc[:, ['DUID', 'TOTALCLEARED']]
        xml_inputs = hist_xml.xml_inputs(cache_folder='test_files/historical_xml_files', interval=interval)
        TOTAL_UNIT_ENERGY_OFFER_VIOLATION = xml_inputs.get_non_intervention_violations()[
            'TOTAL_UNIT_ENERGY_OFFER_VIOLATION']
        bid_availability = xml_inputs.get_unit_volume_bids().loc[:, ['DUID', 'BIDTYPE', 'MAXAVAIL', 'RAMPDOWNRATE',
                                                                     'RAMPUPRATE']]
        bid_availability = bid_availability[bid_availability['BIDTYPE'] == 'ENERGY']
        semi_dispatch_flag = xml_inputs.get_unit_fast_start_parameters().loc[:, ['DUID', 'SEMIDISPATCH']]
        schedualed_units = semi_dispatch_flag[semi_dispatch_flag['SEMIDISPATCH'] == 0.0]
        initial_cons = xml_inputs.get_unit_initial_conditions_dataframe().loc[:, ['DUID', 'INITIALMW']]
        bid_availability = pd.merge(bid_availability, schedualed_units, 'inner', on='DUID')
        bid_availability = pd.merge(bid_availability, dispatch_load, 'inner', on='DUID')
        bid_availability = pd.merge(bid_availability, initial_cons, 'inner', on='DUID')
        bid_availability['RAMPMIN'] = bid_availability['INITIALMW'] - bid_availability['RAMPDOWNRATE'] / 12
        bid_availability['MAXAVAIL'] = np.where(bid_availability['RAMPMIN'] > bid_availability['MAXAVAIL'],
                                                bid_availability['RAMPMIN'], bid_availability['MAXAVAIL'])
        bid_availability['violation'] = np.where(bid_availability['TOTALCLEARED'] > bid_availability['MAXAVAIL'],
                                                 bid_availability['TOTALCLEARED'] - bid_availability['MAXAVAIL'], 0.0)
        measured_violation = bid_availability['violation'].sum()
        assert measured_violation == pytest.approx(TOTAL_UNIT_ENERGY_OFFER_VIOLATION, abs=0.1)


def test_if_schudeled_units_dispatched_above_UIGF():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        # if interval != '2019/01/25 16:15:00':
        #     continue
        print(interval)
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval).loc[:, ['DUID', 'TOTALCLEARED']]
        xml_inputs = hist_xml.xml_inputs(cache_folder='test_files/historical_xml_files', interval=interval)
        UGIF_total_violation = xml_inputs.get_non_intervention_violations()['TOTAL_UGIF_VIOLATION']
        ramp_rates = xml_inputs.get_unit_volume_bids().loc[:, ['DUID', 'BIDTYPE', 'RAMPDOWNRATE']]
        ramp_rates = ramp_rates[ramp_rates['BIDTYPE'] == 'ENERGY']
        initial_cons = xml_inputs.get_unit_initial_conditions_dataframe().loc[:, ['DUID', 'INITIALMW']]
        UGIFs = xml_inputs.get_UGIF_values().loc[:, ['DUID', 'UGIF']]
        availability = pd.merge(UGIFs, dispatch_load, 'inner', on='DUID')
        availability = pd.merge(availability, initial_cons, 'inner', on='DUID')
        availability = pd.merge(availability, ramp_rates, 'inner', on='DUID')
        availability['violation'] = np.where(availability['TOTALCLEARED'] > availability['UGIF'],
                                             availability['TOTALCLEARED'] - availability['UGIF'], 0.0)
        measured_violation = availability['violation'].sum()
        assert measured_violation == pytest.approx(UGIF_total_violation, abs=0.001)


def test_if_ramp_rates_calculated_correctly():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval).loc[:, ['DUID', 'TOTALCLEARED']]
        xml_inputs = hist_xml.xml_inputs(cache_folder='test_files/historical_xml_files', interval=interval)
        TOTAL_RAMP_RATE_VIOLATION = xml_inputs.get_non_intervention_violations()['TOTAL_RAMP_RATE_VIOLATION']
        ramp_rates = xml_inputs.get_unit_volume_bids().loc[:, ['DUID', 'BIDTYPE', 'RAMPDOWNRATE', 'RAMPUPRATE']]
        ramp_rates = ramp_rates[ramp_rates['BIDTYPE'] == 'ENERGY']
        initial_cons = xml_inputs.get_unit_initial_conditions_dataframe().loc[:, ['DUID', 'INITIALMW', 'RAMPDOWNRATE',
                                                                                  'RAMPUPRATE']]
        ramp_rates = pd.merge(ramp_rates, initial_cons, 'left', on='DUID')
        ramp_rates['RAMPDOWNRATE'] = np.where(~ramp_rates['RAMPDOWNRATE_y'].isna(), ramp_rates['RAMPDOWNRATE_y'],
                                              ramp_rates['RAMPDOWNRATE_x'])
        ramp_rates['RAMPUPRATE'] = np.where(~ramp_rates['RAMPUPRATE_y'].isna(), ramp_rates['RAMPUPRATE_y'],
                                            ramp_rates['RAMPUPRATE_x'])
        availability = pd.merge(dispatch_load, ramp_rates, 'inner', on='DUID')
        availability['RAMPMIN'] = availability['INITIALMW'] - availability['RAMPDOWNRATE'] / 12
        availability['RAMPMAX'] = availability['INITIALMW'] + availability['RAMPUPRATE'] / 12
        availability['violation'] = np.where((availability['TOTALCLEARED'] > availability['RAMPMAX']),
                                             availability['TOTALCLEARED'] - availability['RAMPMAX'], 0.0)
        availability['violation'] = np.where((availability['TOTALCLEARED'] < availability['RAMPMIN']),
                                             availability['RAMPMIN'] - availability['TOTALCLEARED'], 0.0)
        measured_violation = availability['violation'].sum()
        assert measured_violation == pytest.approx(TOTAL_RAMP_RATE_VIOLATION, abs=0.1)


def test_fast_start_constraints():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval).loc[:, ['DUID', 'TOTALCLEARED']]
        xml_inputs = hist_xml.xml_inputs(cache_folder='test_files/historical_xml_files', interval=interval)
        fast_start_profiles = xml_inputs.get_unit_fast_start_parameters()
        c1 = historical_unit_limits.fast_start_mode_one_constraints(fast_start_profiles)
        c2 = historical_unit_limits.fast_start_mode_one_constraints(fast_start_profiles)
        c3 = historical_unit_limits.fast_start_mode_one_constraints(fast_start_profiles)
        c4 = historical_unit_limits.fast_start_mode_one_constraints(fast_start_profiles)
        constraints = pd.concat([c1, c2, c3, c4])
        constraints = pd.merge(constraints, dispatch_load, left_on='unit', right_on='DUID')
        constraints['violation'] = np.where((constraints['TOTALCLEARED'] > constraints['max']),
                                            constraints['TOTALCLEARED'] - constraints['max'], 0.0)
        constraints['violation'] = np.where((constraints['TOTALCLEARED'] < constraints['min']),
                                            constraints['min'] - constraints['TOTALCLEARED'], 0.0)
        measured_violation = constraints['violation'].sum()
        TOTAL_FAST_START_VIOLATION = xml_inputs.get_non_intervention_violations()['TOTAL_FAST_START_VIOLATION']
        if measured_violation > 0.0:
            x=1
        assert measured_violation == pytest.approx(TOTAL_FAST_START_VIOLATION, abs=0.1)


def test_fcas_trapezium_scaled_availability():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        # if interval != '2019/01/16 12:20:00':
        #     continue
        print(interval)
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.set_unit_fcas_constraints()
        market.set_unit_limit_constraints()
        market.set_unit_dispatch_to_historical_values(wiggle_room=0.0001)
        market.dispatch(calc_prices=False)
        market.do_fcas_availabilities_match_historical()


def test_slack_in_generic_constraints():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.add_generic_constraints()
        market.set_unit_dispatch_to_historical_values(wiggle_room=0.003)
        market.set_interconnector_flow_to_historical_values()
        market.dispatch(calc_prices=False)
        assert market.is_generic_constraint_slack_correct()


def test_slack_in_generic_constraints_use_fcas_requirements_interface():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        print(interval)
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.add_generic_constraints_fcas_requirements()
        market.set_unit_dispatch_to_historical_values(wiggle_room=0.003)
        market.set_interconnector_flow_to_historical_values()
        market.dispatch(calc_prices=False)
        assert market.is_generic_constraint_slack_correct()
        assert market.is_fcas_constraint_slack_correct()


def test_slack_in_generic_constraints_with_all_features():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        print(interval)
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.add_generic_constraints_fcas_requirements()
        market.set_unit_fcas_constraints()
        market.set_unit_limit_constraints()
        market.set_unit_dispatch_to_historical_values(wiggle_room=0.003)
        market.set_interconnector_flow_to_historical_values()
        market.dispatch(calc_prices=False)
        assert market.is_generic_constraint_slack_correct()
        assert market.is_fcas_constraint_slack_correct()
        assert market.is_regional_demand_meet()


def test_hist_dispatch_values_feasible_with_demand_constraints():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.set_unit_dispatch_to_historical_values(wiggle_room=0.003)
        market.set_interconnector_flow_to_historical_values()
        market.set_region_demand_constraints()
        market.dispatch(calc_prices=False)


def test_hist_dispatch_values_feasible_with_unit_fcas_and_limit_constraints():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.set_unit_dispatch_to_historical_values()
        market.set_interconnector_flow_to_historical_values()
        market.set_unit_fcas_constraints()
        market.set_unit_limit_constraints()
        market.dispatch()


def test_hist_dispatch_values_feasible_with_unit_fcas_constraints():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.set_unit_dispatch_to_historical_values()
        market.set_interconnector_flow_to_historical_values()
        market.set_unit_fcas_constraints()
        market.dispatch()


def test_hist_dispatch_values_feasible_with_unit_limit_constraints():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.set_unit_dispatch_to_historical_values()
        market.set_interconnector_flow_to_historical_values()
        market.set_unit_limit_constraints()
        market.dispatch()


def test_hist_dispatch_values_meet_demand():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.set_unit_dispatch_to_historical_values()
        market.set_interconnector_flow_to_historical_values()
        market.dispatch()
        test_passed = market.is_regional_demand_meet()
        market.con.close()
        assert test_passed


def test_prices_full_featured():
    inputs_database = 'test_files/historical_inputs.db'
    outputs = []
    c = 0
    for interval in get_test_intervals():
        c += 1
        if c > 10:
            break
        print(interval)
        if interval not in ['2019/01/23 14:20:00']:
            continue
        # if interval in ['2019/01/28 03:35:00', '2019/01/28 20:50:00']:
        #     continue
        # if interval in ['2019/01/29 20:40:00']:
        #     break
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.add_generic_constraints_fcas_requirements()
        market.set_unit_fcas_constraints()
        market.set_unit_limit_constraints()
        market.set_region_demand_constraints()
        market.dispatch()
        disp = market.get_dispatch_comparison().sort_values('diff')
        outputs.append(market.get_price_comparison())
    outputs = pd.concat(outputs)
    outputs.to_csv('price_comp.csv')


class HistoricalSpotMarket:
    def __init__(self, inputs_database, interval):
        self.con = sqlite3.connect(inputs_database)
        self.inputs_manager = hi.DBManager(connection=self.con)
        self.interval = interval
        self.services = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                         'LOWERREG', 'RAISEREG']
        self.service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                     'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                     'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min',
                                     'ENERGY': 'energy'}
        self.market = markets.Spot()

    def add_unit_bids_to_market(self):

        self.xml_inputs = hist_xml.xml_inputs(cache_folder='test_files/historical_xml_files', interval=self.interval)
        initial_cons = self.xml_inputs.get_unit_initial_conditions_dataframe()
        self.initial_cons = initial_cons

        # Unit info.
        DUDETAILSUMMARY = self.inputs_manager.DUDETAILSUMMARY.get_data(self.interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = self.inputs_manager.BIDPEROFFER_D.get_data(self.interval)
        BIDPEROFFER_D = xml_inputs.get_unit_volume_bids()
        BIDDAYOFFER_D = self.inputs_manager.BIDDAYOFFER_D.get_data(self.interval)

        # The unit operating conditions at the start of the historical interval.
        DISPATCHLOAD = self.inputs_manager.DISPATCHLOAD.get_data(self.interval)
        DISPATCHLOAD['AGCSTATUS'] = pd.to_numeric(DISPATCHLOAD['AGCSTATUS'])
        # DISPATCHLOAD = pd.merge(DISPATCHLOAD, initial_cons.loc[:, ['DUID', 'INITIALMW', 'RAMPUPRATE', 'RAMPDOWNRATE']], 'left', on='DUID')
        # DISPATCHLOAD['RAMPUPRATE'] = np.where((~DISPATCHLOAD['RAMPUPRATE_y'].isna()) &
        #                                       (DISPATCHLOAD['RAMPUPRATE_y'] < DISPATCHLOAD['RAMPUPRATE_x']),
        #                                       DISPATCHLOAD['RAMPUPRATE_y'],
        #                                       DISPATCHLOAD['RAMPUPRATE_x'])
        # DISPATCHLOAD['RAMPDOWNRATE'] = np.where((~DISPATCHLOAD['RAMPDOWNRATE_y'].isna()) &
        #                                         (DISPATCHLOAD['RAMPDOWNRATE_y'] < DISPATCHLOAD['RAMPDOWNRATE_x']),
        #                                         DISPATCHLOAD['RAMPDOWNRATE_y'],
        #                                         DISPATCHLOAD['RAMPDOWNRATE_x'])
        # DISPATCHLOAD = DISPATCHLOAD.drop(['RAMPUPRATE_y', 'RAMPUPRATE_x', 'RAMPDOWNRATE_y', 'RAMPDOWNRATE_x'], axis=1)
        # DISPATCHLOAD['INITIALMW'] = np.where(~DISPATCHLOAD['INITIALMW_y'].isna(), DISPATCHLOAD['INITIALMW_y'],
        #                                       DISPATCHLOAD['INITIALMW_x'])
        # DISPATCHLOAD = DISPATCHLOAD.drop(['INITIALMW_y', 'INITIALMW_x'], axis=1)
        self.unit_limits = hi.determine_unit_limits(DISPATCHLOAD, BIDPEROFFER_D)

        # FCAS bid prepocessing
        BIDPEROFFER_D = hi.scaling_for_agc_enablement_limits(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = hi.scaling_for_agc_ramp_rates(BIDPEROFFER_D, initial_cons)
        BIDPEROFFER_D = hi.scaling_for_uigf(BIDPEROFFER_D, DISPATCHLOAD, DUDETAILSUMMARY)
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.enforce_preconditions_for_enabling_fcas(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD, self.unit_limits.loc[:, ['unit', 'capacity']])
        self.BIDPEROFFER_D, self.BIDDAYOFFER_D = hi.use_historical_actual_availability_to_filter_fcas_bids(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD)

        # Change bidding data to conform to nempy input format.
        volume_bids = hi.format_volume_bids(self.BIDPEROFFER_D)
        price_bids = hi.format_price_bids(self.BIDDAYOFFER_D)

        # Add generators to the market.
        self.market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

        # Set volume of each bids.
        volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info['unit']))]
        self.market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                             '6', '7', '8', '9', '10']])

        # Set prices of each bid.
        price_bids = price_bids[price_bids['unit'].isin(list(unit_info['unit']))]
        self.market.set_unit_price_bids(price_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                           '6', '7', '8', '9', '10']])

    def set_unit_limit_constraints(self):
        # Set unit operating limits.
        x = self.xml_inputs.get_unit_fast_start_parameters()
        self.market.set_unit_capacity_constraints(self.unit_limits.loc[:, ['unit', 'capacity']])
        self.market.set_unit_ramp_up_constraints(self.unit_limits.loc[:, ['unit', 'initial_output', 'ramp_up_rate']])
        self.market.set_unit_ramp_down_constraints(
            self.unit_limits.loc[:, ['unit', 'initial_output', 'ramp_down_rate']])

    def set_unit_fcas_constraints(self):
        # Create constraints that enforce the top of the FCAS trapezium.
        fcas_trapeziums = hi.format_fcas_trapezium_constraints(self.BIDPEROFFER_D)
        fcas_availability = fcas_trapeziums.loc[:, ['unit', 'service', 'max_availability']]
        self.market.set_fcas_max_availability(fcas_availability)

        # Create constraints the enforce the lower and upper slope of the FCAS regulation
        # service trapeziums.
        regulation_trapeziums = fcas_trapeziums[fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
        self.market.set_energy_and_regulation_capacity_constraints(regulation_trapeziums)
        self.market.make_constraints_elastic('energy_and_regulation_capacity', 14000.0)
        initial_cons = self.initial_cons.loc[:, ['DUID', 'INITIALMW', 'RAMPUPRATE', 'RAMPDOWNRATE']]
        units_with_scada_ramp_rates = list(
            initial_cons[(~initial_cons['RAMPUPRATE'].isna()) & initial_cons['RAMPUPRATE'] != 0]['DUID'])
        initial_cons = initial_cons[initial_cons['DUID'].isin(units_with_scada_ramp_rates)]
        initial_cons.columns = ['unit', 'initial_output', 'ramp_up_rate', 'ramp_down_rate']
        reg_units = regulation_trapeziums.loc[:, ['unit', 'service']]

        reg_units = pd.merge(initial_cons, regulation_trapeziums.loc[:, ['unit', 'service']], 'inner', on='unit')
        reg_units = reg_units[(reg_units['service'] == 'raise_reg') & (~reg_units['ramp_up_rate'].isna()) |
                              (reg_units['service'] == 'lower_reg') & (~reg_units['ramp_down_rate'].isna())]
        reg_units = reg_units.loc[:, ['unit', 'service']]
        initial_cons = initial_cons.fillna(0)
        self.market.set_joint_ramping_constraints(reg_units, initial_cons)
        self.market.make_constraints_elastic('joint_ramping', 14000.0)

        # Create constraints that enforce the lower and upper slope of the FCAS contingency
        # trapezium. These constrains also scale slopes of the trapezium to ensure the
        # co-dispatch of contingency and regulation services is technically feasible.
        contingency_trapeziums = fcas_trapeziums[~fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
        self.market.set_joint_capacity_constraints(contingency_trapeziums)
        self.market.make_constraints_elastic('joint_capacity', 14000.0)

    def set_region_demand_constraints(self):
        # Set regional demand.
        # Demand on regional basis.
        DISPATCHREGIONSUM = self.inputs_manager.DISPATCHREGIONSUM.get_data(self.interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)
        self.market.set_demand_constraints(regional_demand.loc[:, ['region', 'demand']])

    def add_interconnectors_to_market(self):
        interconnector_inputs = hii.HistoricalInterconnectors(self.inputs_manager, self.interval)
        interconnector_inputs.add_loss_model()
        interconnector_inputs.add_market_interconnector_transmission_loss_factors()
        interconnector_inputs.split_bass_link_to_enable_dynamic_from_region_loss_shares()
        interconnectors = interconnector_inputs.get_interconnector_definitions()
        loss_functions, interpolation_break_points = interconnector_inputs.get_interconnector_loss_model()
        self.market.set_interconnectors(interconnectors)
        self.market.set_interconnector_losses(loss_functions, interpolation_break_points)

    def add_generic_constraints(self):
        DISPATCHCONSTRAINT = self.inputs_manager.DISPATCHCONSTRAINT.get_data(self.interval)
        DUDETAILSUMMARY = self.inputs_manager.DUDETAILSUMMARY.get_data(self.interval)
        GENCONDATA = self.inputs_manager.GENCONDATA.get_data(self.interval)
        SPDINTERCONNECTORCONSTRAINT = self.inputs_manager.SPDINTERCONNECTORCONSTRAINT.get_data(self.interval)
        SPDREGIONCONSTRAINT = self.inputs_manager.SPDREGIONCONSTRAINT.get_data(self.interval)
        SPDCONNECTIONPOINTCONSTRAINT = self.inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.get_data(self.interval)

        generic_rhs = hi.format_generic_constraints_rhs_and_type(DISPATCHCONSTRAINT, GENCONDATA)
        unit_generic_lhs = hi.format_generic_unit_lhs(SPDCONNECTIONPOINTCONSTRAINT, DUDETAILSUMMARY)
        region_generic_lhs = hi.format_generic_region_lhs(SPDREGIONCONSTRAINT)

        interconnector_generic_lhs = hi.format_generic_interconnector_lhs(SPDINTERCONNECTORCONSTRAINT)
        bass_link, interconnector_generic_lhs = self._split_out_bass_link(interconnector_generic_lhs)
        bass_link_forward_direction = hii.create_forward_flow_interconnectors(bass_link)
        bass_link_reverse_direction = hii.create_reverse_flow_interconnectors(bass_link)
        interconnector_generic_lhs = pd.concat([interconnector_generic_lhs, bass_link_forward_direction,
                                                bass_link_reverse_direction])

        self.market.set_generic_constraints(generic_rhs)
        self.market.make_constraints_elastic('generic', violation_cost=0.0)
        self.market.link_units_to_generic_constraints(unit_generic_lhs)
        self.market.link_regions_to_generic_constraints(region_generic_lhs)
        self.market.link_interconnectors_to_generic_constraints(interconnector_generic_lhs)

    def add_generic_constraints_fcas_requirements(self):
        DISPATCHCONSTRAINT = self.inputs_manager.DISPATCHCONSTRAINT.get_data(self.interval)
        DUDETAILSUMMARY = self.inputs_manager.DUDETAILSUMMARY.get_data(self.interval)
        GENCONDATA = self.inputs_manager.GENCONDATA.get_data(self.interval)
        SPDINTERCONNECTORCONSTRAINT = self.inputs_manager.SPDINTERCONNECTORCONSTRAINT.get_data(self.interval)
        SPDREGIONCONSTRAINT = self.inputs_manager.SPDREGIONCONSTRAINT.get_data(self.interval)
        SPDCONNECTIONPOINTCONSTRAINT = self.inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.get_data(self.interval)

        generic_rhs = hi.format_generic_constraints_rhs_and_type(DISPATCHCONSTRAINT, GENCONDATA)
        unit_generic_lhs = hi.format_generic_unit_lhs(SPDCONNECTIONPOINTCONSTRAINT, DUDETAILSUMMARY)
        region_generic_lhs = hi.format_generic_region_lhs(SPDREGIONCONSTRAINT)

        interconnector_generic_lhs = hi.format_generic_interconnector_lhs(SPDINTERCONNECTORCONSTRAINT)
        bass_link, interconnector_generic_lhs = self._split_out_bass_link(interconnector_generic_lhs)
        bass_link_forward_direction = hii.create_forward_flow_interconnectors(bass_link)
        bass_link_reverse_direction = hii.create_reverse_flow_interconnectors(bass_link)
        interconnector_generic_lhs = pd.concat([interconnector_generic_lhs, bass_link_forward_direction,
                                                bass_link_reverse_direction])

        violation_cost = GENCONDATA.loc[:, ['GENCONID', 'GENERICCONSTRAINTWEIGHT']]
        violation_cost['cost'] = violation_cost['GENERICCONSTRAINTWEIGHT'] * 14000
        violation_cost = violation_cost.loc[:, ['GENCONID', 'cost']]
        violation_cost.columns = ['set', 'cost']

        fcas_requirements = hi.format_fcas_market_requirements(SPDREGIONCONSTRAINT, DISPATCHCONSTRAINT, GENCONDATA)
        self.market.set_fcas_requirements_constraints(fcas_requirements)
        self.market.make_constraints_elastic('fcas', violation_cost=violation_cost)

        generic_rhs = generic_rhs[~generic_rhs['set'].isin(list(fcas_requirements['set']))]
        region_generic_lhs = region_generic_lhs[~region_generic_lhs['set'].isin(list(fcas_requirements['set']))]
        self.market.set_generic_constraints(generic_rhs)
        self.market.make_constraints_elastic('generic', violation_cost=violation_cost)
        self.market.link_units_to_generic_constraints(unit_generic_lhs)
        self.market.link_interconnectors_to_generic_constraints(interconnector_generic_lhs)
        self.market.link_regions_to_generic_constraints(region_generic_lhs)

    def set_unit_dispatch_to_historical_values(self, wiggle_room=0.001):
        DISPATCHLOAD = self.inputs_manager.DISPATCHLOAD.get_data(self.interval)

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + self.services]
        bounds.columns = ['unit'] + self.services

        bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=self.services, type_name='service',
                                  value_name='dispatched')

        bounds['service'] = bounds['service'].apply(lambda x: self.service_name_mapping[x])

        decision_variables = self.market.decision_variables['bids'].copy()

        decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

        decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

        def last_bids(df):
            return df.iloc[1:]

        decision_variables_remaining_bids = \
            decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

        decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched'] - wiggle_room
        decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched'] + wiggle_room
        decision_variables_first_bid['lower_bound'] = np.where(decision_variables_first_bid['lower_bound'] < 0.0, 0.0,
                                                               decision_variables_first_bid['lower_bound'])
        decision_variables_first_bid['upper_bound'] = np.where(decision_variables_first_bid['upper_bound'] < 0.0, 0.0,
                                                               decision_variables_first_bid['upper_bound'])
        decision_variables_remaining_bids['lower_bound'] = 0.0
        decision_variables_remaining_bids['upper_bound'] = 0.0

        decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

        self.market.decision_variables['bids'] = decision_variables

    def set_interconnector_flow_to_historical_values(self, wiggle_room=0.1):
        # Historical interconnector dispatch
        DISPATCHINTERCONNECTORRES = self.inputs_manager.DISPATCHINTERCONNECTORRES.get_data(self.interval)
        interconnector_flow = DISPATCHINTERCONNECTORRES.loc[:, ['INTERCONNECTORID', 'MWFLOW']]
        interconnector_flow.columns = ['interconnector', 'flow']

        bass_link, loss_functions = self._split_out_bass_link(interconnector_flow)
        bass_link = hii.split_interconnector_flow_into_two_directional_links(bass_link)
        interconnector_flow = pd.concat([interconnector_flow, bass_link])

        flow_variables = self.market.decision_variables['interconnectors']
        flow_variables = pd.merge(flow_variables, interconnector_flow, 'inner', on=['interconnector'])
        flow_variables['lower_bound'] = flow_variables['flow'] - wiggle_room
        flow_variables['upper_bound'] = flow_variables['flow'] + wiggle_room
        flow_variables = flow_variables.drop(['flow'], axis=1)

        self.market.decision_variables['interconnectors'] = flow_variables

    @staticmethod
    def _split_out_bass_link(interconnectors):
        bass_link = interconnectors[interconnectors['interconnector'] == 'T-V-MNSP1']
        interconnectors = interconnectors[interconnectors['interconnector'] != 'T-V-MNSP1']
        return bass_link, interconnectors

    def dispatch(self, calc_prices=True):
        self.market.dispatch(price_market_constraints=calc_prices)

    def is_regional_demand_meet(self, tolerance=0.5):
        DISPATCHREGIONSUM = self.inputs_manager.DISPATCHREGIONSUM.get_data(self.interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)
        region_summary = self.market.get_region_dispatch_summary()
        region_summary = pd.merge(region_summary, regional_demand, on='region')
        region_summary['calc_demand'] = region_summary['dispatch'] + region_summary['inflow'] \
                                        - region_summary['interconnector_losses'] - \
                                        region_summary['transmission_losses']
        region_summary['diff'] = region_summary['calc_demand'] - region_summary['demand']
        region_summary['no_error'] = region_summary['diff'].abs() < tolerance
        return region_summary['no_error'].all()

    def is_generic_constraint_slack_correct(self):

        def calc_slack(rhs, lhs, type):
            if type == '<=':
                slack = rhs - lhs
            elif type == '>=':
                slack = lhs - rhs
            else:
                slack = 0.0
            if slack < 0.0:
                slack = 0.0
            return slack

        DISPATCHCONSTRAINT = self.inputs_manager.DISPATCHCONSTRAINT.get_data(self.interval)
        generic_cons_slack = self.market.constraints_rhs_and_type['generic']
        generic_cons_slack = pd.merge(generic_cons_slack, DISPATCHCONSTRAINT, left_on='set',
                                      right_on='CONSTRAINTID')
        generic_cons_slack['aemo_slack'] = (generic_cons_slack['RHS'] - generic_cons_slack['LHS'])
        generic_cons_slack['aemo_slack'] = \
            generic_cons_slack.apply(lambda x: calc_slack(x['RHS'], x['LHS'], x['type']), axis=1)
        generic_cons_slack['comp'] = (generic_cons_slack['aemo_slack'] - generic_cons_slack['slack']).abs()
        generic_cons_slack['no_error'] = generic_cons_slack['comp'] < 0.9
        return generic_cons_slack['no_error'].all()

    def is_fcas_constraint_slack_correct(self):

        def calc_slack(rhs, lhs, type):
            if type == '<=':
                slack = rhs - lhs
            elif type == '>=':
                slack = lhs - rhs
            else:
                slack = 0.0
            if slack < 0.0:
                slack = 0.0
            return slack

        DISPATCHCONSTRAINT = self.inputs_manager.DISPATCHCONSTRAINT.get_data(self.interval)
        generic_cons_slack = self.market.market_constraints_rhs_and_type['fcas']
        generic_cons_slack = pd.merge(generic_cons_slack, DISPATCHCONSTRAINT, left_on='set',
                                      right_on='CONSTRAINTID')
        generic_cons_slack['aemo_slack'] = (generic_cons_slack['RHS'] - generic_cons_slack['LHS'])
        generic_cons_slack['aemo_slack'] = \
            generic_cons_slack.apply(lambda x: calc_slack(x['RHS'], x['LHS'], x['type']), axis=1)
        generic_cons_slack['comp'] = (generic_cons_slack['aemo_slack'] - generic_cons_slack['slack']).abs()
        generic_cons_slack['no_error'] = generic_cons_slack['comp'] < 0.9
        return generic_cons_slack['no_error'].all()

    def get_price_comparison(self):
        energy_prices = self.market.get_energy_prices()
        energy_prices['time'] = self.interval
        energy_prices['service'] = 'energy'
        fcas_prices = self.market.get_fcas_prices()
        fcas_prices['time'] = self.interval
        prices = pd.concat([energy_prices, fcas_prices])

        price_to_service = {'RRP': 'energy', 'RAISE6SECRRP': 'raise_6s', 'RAISE60SECRRP': 'raise_60s',
                            'RAISE5MINRRP': 'raise_5min', 'RAISEREGRRP': 'raise_reg', 'LOWER6SECRRP': 'lower_6s',
                            'LOWER60SECRRP': 'lower_60s', 'LOWER5MINRRP': 'lower_5min', 'LOWERREGRRP': 'lower_reg'}
        price_columns = list(price_to_service.keys())
        historical_prices = self.inputs_manager.DISPATCHPRICE.get_data(self.interval)
        historical_prices = hf.stack_columns(historical_prices, cols_to_keep=['SETTLEMENTDATE', 'REGIONID'],
                                             cols_to_stack=price_columns, type_name='service',
                                             value_name='RRP')
        historical_prices['service'] = historical_prices['service'].apply(lambda x: price_to_service[x])
        historical_prices = historical_prices.loc[:, ['SETTLEMENTDATE', 'REGIONID', 'service', 'RRP']]
        historical_prices.columns = ['time', 'region', 'service', 'hist_price']
        prices = pd.merge(prices, historical_prices, on=['time', 'region', 'service'])
        return prices

    def get_dispatch_comparison(self):
        DISPATCHLOAD = self.inputs_manager.DISPATCHLOAD.get_data(self.interval)
        nempy_dispatch = self.market.get_unit_dispatch()
        comp = pd.merge(nempy_dispatch[nempy_dispatch['service'] == 'energy'],
                        DISPATCHLOAD.loc[:, ['DUID', 'TOTALCLEARED']],
                        'left', left_on='unit', right_on='DUID')
        comp['diff'] = comp['dispatch'] - comp['TOTALCLEARED']
        comp = pd.merge(comp, self.market.unit_info.loc[:, ['unit', 'dispatch_type']], on='unit')
        comp['diff'] = np.where(comp['dispatch_type'] == 'load', comp['diff'] * -1, comp['diff'])
        return comp

    def do_fcas_availabilities_match_historical(self):
        DISPATCHLOAD = self.inputs_manager.DISPATCHLOAD.get_data(self.interval)
        availabilities = ['RAISE6SECACTUALAVAILABILITY', 'RAISE60SECACTUALAVAILABILITY',
                          'RAISE5MINACTUALAVAILABILITY', 'RAISEREGACTUALAVAILABILITY',
                          'LOWER6SECACTUALAVAILABILITY', 'LOWER60SECACTUALAVAILABILITY',
                          'LOWER5MINACTUALAVAILABILITY', 'LOWERREGACTUALAVAILABILITY']

        availabilities_mapping = {'RAISEREGACTUALAVAILABILITY': 'raise_reg',
                                  'LOWERREGACTUALAVAILABILITY': 'lower_reg',
                                  'RAISE6SECACTUALAVAILABILITY': 'raise_6s',
                                  'RAISE60SECACTUALAVAILABILITY': 'raise_60s',
                                  'RAISE5MINACTUALAVAILABILITY': 'raise_5min',
                                  'LOWER6SECACTUALAVAILABILITY': 'lower_6s',
                                  'LOWER60SECACTUALAVAILABILITY': 'lower_60s',
                                  'LOWER5MINACTUALAVAILABILITY': 'lower_5min'}

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + availabilities]
        bounds.columns = ['unit'] + availabilities

        availabilities = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=availabilities,
                                          type_name='service', value_name='availability')

        availabilities['service'] = availabilities['service'].apply(lambda x: availabilities_mapping[x])

        output = self.market.get_fcas_availability()
        output.columns = ['unit', 'service', 'availability_measured']

        availabilities = pd.merge(availabilities, output, 'left', on=['unit', 'service'])

        availabilities['availability_measured'] = availabilities['availability_measured'].fillna(0)

        availabilities['error'] = availabilities['availability_measured'] - availabilities['availability']

        availabilities['match'] = availabilities['error'].abs() < 0.1
        availabilities = availabilities.sort_values('match')
        return availabilities
