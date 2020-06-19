import numpy as np
import pandas as pd
from nempy import check, market_constraints, objective_function, solver_interface, unit_constraints, variable_ids, \
    interconnectors as inter, fcas_constraints, elastic_constraints, helper_functions as hf
from nempy import spot_markert_backend as smb


class Spot:
    """Class for constructing and dispatching the spot market on an interval basis."""

    def __init__(self, dispatch_interval=5, market_ceiling_price=14000.0, market_floor_price=-1000.0):
        self.dispatch_interval = dispatch_interval
        self.market_ceiling_price = market_ceiling_price
        self.market_floor_price = market_floor_price
        self.unit_info = None
        self.decision_variables = {}
        self.variable_to_constraint_map = {'regional': {}, 'unit_level': {}}
        self.constraint_to_variable_map = {'regional': {}, 'unit_level': {}}
        self.lhs_coefficients = {}
        self.generic_constraint_lhs = {}
        self.constraints_rhs_and_type = {}
        self.constraints_dynamic_rhs_and_type = {}
        self.market_constraints_rhs_and_type = {}
        self.objective_function_components = {}
        self.interconnector_directions = None
        self.interconnector_loss_shares = None
        self.next_variable_id = 0
        self.next_constraint_id = 0
        self.check = True

    @check.required_columns('unit_info', ['unit', 'region'])
    @check.allowed_columns('unit_info', ['unit', 'region', 'loss_factor', 'dispatch_type'])
    @check.column_data_types('unit_info', {'unit': str, 'region': str, 'loss_factor': np.float64,
                                           'dispatch_type': str})
    @check.column_values_must_be_real('unit_info', ['loss_factor'])
    @check.column_values_not_negative('unit_info', ['loss_factor'])
    def set_unit_info(self, unit_info):
        """Add general information required.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Parameters
        ----------
        unit_info : pd.DataFrame
            Information on a unit basis, not all columns are required.

            ===========    ============================================================================================
            Columns:       Description:
            unit           unique identifier of a dispatch unit, required (as `str`)
            region         location of unit, required (as `str`)
            loss_factor    marginal, average or combined loss factors, \n
                           :download:`see AEMO doc <../../docs/pdfs/Treatment_of_Loss_Factors_in_the_NEM.pdf>`, \n
                           optional (as `np.int64`)
            dispatch_type  "load" or "generator" (as `str`)
            =============  ============================================================================================

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If the column 'units' or 'regions' is missing.
            UnexpectedColumn
                There is a column that is not 'units', 'regions' or 'loss_factor'.
            ColumnValues
                If there are inf, null or negative values in the 'loss_factor' column."""

        if 'dispatch_type' not in unit_info.columns:
            unit_info['dispatch_type'] = 'generator'
        self.unit_info = unit_info

    @check.required_columns('volume_bids', ['unit'])
    @check.allowed_columns('volume_bids', ['unit', 'service', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    @check.repeated_rows('volume_bids', ['unit', 'service'])
    @check.column_data_types('volume_bids', {'unit': str, 'service': str, 'else': np.float64})
    @check.column_values_must_be_real('volume_bids', ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    @check.column_values_not_negative('volume_bids', ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    @check.all_units_have_info
    def set_unit_volume_bids(self, volume_bids):
        """Creates the decision variables corresponding to energy bids.

        Variables are created by reserving a variable id (as `int`) for each bid. Bids with a volume of 0 MW do not
        have a variable created. The lower bound of the variables are set to zero and the upper bound to the bid
        volume, the variable type is set to continuous.

        Also clears any preexisting constraints sets or objective functions that depend on the energy bid decision
        variables.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        The market should now have the variables.

        >>> print(simple_market.decision_variables['bids'])
          unit capacity_band service  variable_id  lower_bound  upper_bound        type
        0    A             1  energy            0          0.0         20.0  continuous
        1    A             2  energy            1          0.0         20.0  continuous
        2    A             3  energy            2          0.0          5.0  continuous
        3    B             1  energy            3          0.0         50.0  continuous
        4    B             2  energy            4          0.0         30.0  continuous
        5    B             3  energy            5          0.0         10.0  continuous

        A mapping of these variables to constraints acting on that unit and service should also exist.

        >>> print(simple_market.variable_to_constraint_map['unit_level']['bids'])
           variable_id unit service  coefficient
        0            0    A  energy          1.0
        1            1    A  energy          1.0
        2            2    A  energy          1.0
        3            3    B  energy          1.0
        4            4    B  energy          1.0
        5            5    B  energy          1.0

        A mapping of these variables to constraints acting on the units region and service should also exist.

        >>> print(simple_market.variable_to_constraint_map['regional']['bids'])
           variable_id region service  coefficient
        0            0    NSW  energy          1.0
        1            1    NSW  energy          1.0
        2            2    NSW  energy          1.0
        3            3    NSW  energy          1.0
        4            4    NSW  energy          1.0
        5            5    NSW  energy          1.0

        Parameters
        ----------
        volume_bids : pd.DataFrame
            Bids by unit, in MW, can contain up to 10 bid bands, these should be labeled '1' to '10'.

            ========  ================================================================
            Columns:  Description:
            unit      unique identifier of a dispatch unit (as `str`)
            service   the service being provided, optional, if missing energy assumed
                      (as `str`)
            1         bid volume in the 1st band, in MW (as `np.float64`)
            2         bid volume in the 2nd band, in MW (as `np.float64`)
              :
            10         bid volume in the nth band, in MW (as `np.float64`)
            ========  ================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If the column 'units' is missing or there are no bid bands.
            UnexpectedColumn
                There is a column that is not 'units' or '1' to '10'.
            ColumnValues
                If there are inf, null or negative values in the bid band columns.
        """
        self.decision_variables['bids'], variable_to_unit_level_constraint_map, variable_to_regional_constraint_map = \
            variable_ids.bids(volume_bids, self.unit_info, self.next_variable_id)
        self.variable_to_constraint_map['regional']['bids'] = variable_to_regional_constraint_map
        self.variable_to_constraint_map['unit_level']['bids'] = variable_to_unit_level_constraint_map
        self.next_variable_id = max(self.decision_variables['bids']['variable_id']) + 1

    @check.energy_bid_ids_exist
    @check.required_columns('price_bids', ['unit'])
    @check.allowed_columns('price_bids', ['unit', 'service', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    @check.repeated_rows('price_bids', ['unit', 'service'])
    @check.column_data_types('price_bids', {'unit': str, 'service': str, 'else': np.float64})
    @check.column_values_must_be_real('price_bids', ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    @check.bid_prices_monotonic_increasing
    def set_unit_price_bids(self, price_bids):
        """Creates the objective function costs corresponding to energy bids.

        If no loss factors have been provided as part of the unit information when the model was initialised then the
        costs in the objective function are as bid. If loss factors are provided then the bid costs are referred to the
        regional reference node by dividing by the loss factor.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of prices for the bids. Bids for each unit need to be monotonically increasing.

        >>> price_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [50.0, 100.0],
        ...     '2': [100.0, 130.0],
        ...     '3': [100.0, 150.0]})

        Create the objective function components corresponding to the the energy bids.

        >>> simple_market.set_unit_price_bids(price_bids)

        The market should now have costs.

        >>> print(simple_market.objective_function_components['bids'])
           variable_id unit service capacity_band   cost
        0            0    A  energy             1   50.0
        1            1    A  energy             2  100.0
        2            2    A  energy             3  100.0
        3            3    B  energy             1  100.0
        4            4    B  energy             2  130.0
        5            5    B  energy             3  150.0

        Parameters
        ----------
        price_bids : pd.DataFrame
            Bids by unit, in $/MW, can contain up to 10 bid bands.

            ========  ===============================================================
            Columns:  Description:
            unit      unique identifier of a dispatch unit (as `str`)
            service   the service being provided, optional, if missing energy assumed
                      (as `str`)
            1         bid price in the 1st band, in $/MW (as `np.float64`)
            2         bid price in the 2nd band, in $/MW (as `np.float64`)
            n         bid price in the nth band, in $/MW (as `np.float64`)
            ========  ===============================================================

        Returns
        -------
        None

        Raises
        ------
            ModelBuildError
                If the volume bids have not been set yet.
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If the column 'units' is missing or there are no bid bands.
            UnexpectedColumn
                There is a column that is not 'units' or '1' to '10'.
            ColumnValues
                If there are inf, -inf or null values in the bid band columns.
            BidsNotMonotonicIncreasing
                If the bids band price for all units are not monotonic increasing.
        """
        energy_objective_function = objective_function.bids(self.decision_variables['bids'], price_bids)
        if 'loss_factor' in self.unit_info.columns:
            energy_objective_function = objective_function.scale_by_loss_factors(energy_objective_function,
                                                                                 self.unit_info)
        self.objective_function_components['bids'] = \
            energy_objective_function.loc[:, ['variable_id', 'unit', 'service', 'capacity_band', 'cost']]

    @check.energy_bid_ids_exist
    @check.required_columns('unit_limits', ['unit', 'capacity'])
    @check.allowed_columns('unit_limits', ['unit', 'capacity'])
    @check.repeated_rows('unit_limits', ['unit'])
    @check.column_data_types('unit_limits', {'unit': str, 'else': np.float64})
    @check.column_values_must_be_real('unit_limits', ['capacity'])
    @check.column_values_not_negative('unit_limits', ['capacity'])
    def set_unit_capacity_constraints(self, unit_limits):
        """Creates constraints that limit unit output based on capacity.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of unit capacities.

        >>> unit_limits = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'capacity': [60.0, 100.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_unit_capacity_constraints(unit_limits)

        The market should now have a set of constraints.

        >>> print(simple_market.constraints_rhs_and_type['unit_capacity'])
          unit  constraint_id type    rhs
        0    A              0   <=   60.0
        1    B              1   <=  100.0

        ... and a mapping of those constraints to the variable types on the lhs.

        >>> print(simple_market.constraint_to_variable_map['unit_level']['unit_capacity'])
           constraint_id unit service  coefficient
        0              0    A  energy          1.0
        1              1    B  energy          1.0


        Parameters
        ----------
        unit_limits : pd.DataFrame
            Capacity by unit.

            ========  =====================================================================================
            Columns:  Description:
            unit      unique identifier of a dispatch unit (as `str`)
            capacity  The maximum output of the unit if unconstrained by ramp rate, in MW (as `np.float64`)
            ========  =====================================================================================

        Returns
        -------
        None

        Raises
        ------
            ModelBuildError
                If the volume bids have not been set yet.
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If the column 'units' or 'capacity' is missing.
            UnexpectedColumn
                There is a column that is not 'units' or 'capacity'.
            ColumnValues
                If there are inf, null or negative values in the bid band columns.
        """
        # 1. Create the constraints
        rhs_and_type, variable_map = unit_constraints.capacity(unit_limits, self.next_constraint_id)
        # 2. Save constraint details.
        self.constraints_rhs_and_type['unit_capacity'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['unit_capacity'] = variable_map
        # 3. Update the constraint and variable id counter
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.energy_bid_ids_exist
    @check.required_columns('unit_limits', ['unit', 'initial_output', 'ramp_up_rate'])
    @check.allowed_columns('unit_limits', ['unit', 'initial_output', 'ramp_up_rate'])
    @check.repeated_rows('unit_limits', ['unit'])
    @check.column_data_types('unit_limits', {'unit': str, 'else': np.float64})
    @check.column_values_must_be_real('unit_limits', ['ramp_up_rate'])
    @check.column_values_not_negative('unit_limits', ['ramp_up_rate'])
    def set_unit_ramp_up_constraints(self, unit_limits):
        """Creates constraints on unit output based on ramp up rate.

        Will constrain the unit output to be <= initial_output + (ramp_up_rate / (dispatch_interval / 60)).

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance, we set the dispatch interval to 30 min, by default it would be 5 min.

        >>> simple_market = markets.Spot(dispatch_interval=30)

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of unit ramp up rates.

        >>> unit_limits = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'initial_output': [20.0, 50.0],
        ...     'ramp_up_rate': [30.0, 100.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_unit_ramp_up_constraints(unit_limits)

        The market should now have a set of constraints.

        >>> print(simple_market.constraints_rhs_and_type['ramp_up'])
          unit  constraint_id type    rhs
        0    A              0   <=   35.0
        1    B              1   <=  100.0

        ... and a mapping of those constraints to variable type for the lhs.

        >>> print(simple_market.constraint_to_variable_map['unit_level']['ramp_up'])
           constraint_id unit service  coefficient
        0              0    A  energy          1.0
        1              1    B  energy          1.0

        Parameters
        ----------
        unit_limits : pd.DataFrame
            Capacity by unit.

            ==============  =====================================================================================
            Columns:        Description:
            unit            unique identifier of a dispatch unit (as `str`)
            initial_output  the output of the unit at the start of the dispatch interval, in MW (as `np.float64`)
            ramp_up_rate    the maximum rate at which the unit can increase output, in MW/h (as `np.float64`)
            ==============  =====================================================================================

        Returns
        -------
        None

        Raises
        ------
            ModelBuildError
                If the volume bids have not been set yet.
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If the column 'units', 'initial_output' or 'ramp_up_rate' is missing.
            UnexpectedColumn
                There is a column that is not 'units', 'initial_output' or 'ramp_up_rate'.
            ColumnValues
                If there are inf, null or negative values in the bid band columns.
        """
        # 1. Create the constraints
        rhs_and_type, variable_map = unit_constraints.ramp_up(unit_limits, self.next_constraint_id,
                                                              self.dispatch_interval)
        # 2. Save constraint details.
        self.constraints_rhs_and_type['ramp_up'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['ramp_up'] = variable_map
        # 3. Update the constraint and variable id counter
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('unit_limits', ['unit', 'initial_output', 'ramp_down_rate'])
    @check.allowed_columns('unit_limits', ['unit', 'initial_output', 'ramp_down_rate'])
    @check.repeated_rows('unit_limits', ['unit'])
    @check.column_data_types('unit_limits', {'unit': str, 'else': np.float64})
    @check.column_values_must_be_real('unit_limits', ['initial_output', 'ramp_down_rate'])
    @check.column_values_not_negative('unit_limits', ['ramp_down_rate'])
    def set_unit_ramp_down_constraints(self, unit_limits):
        """Creates constraints on unit output based on ramp down rate.

        Will constrain the unit output to be >= initial_output - (ramp_down_rate / (dispatch_interval / 60)).

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance, we set the dispatch interval to 30 min, by default it would be 5 min.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of unit ramp down rates, also need to provide the initial output of the units at the start of
        dispatch interval.

        >>> unit_limits = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'initial_output': [20.0, 50.0],
        ...     'ramp_down_rate': [20.0, 10.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_unit_ramp_down_constraints(unit_limits)

        The market should now have a set of constraints.

        >>> print(simple_market.constraints_rhs_and_type['ramp_down'])
          unit  constraint_id type        rhs
        0    A              0   >=  18.333333
        1    B              1   >=  49.166667

        ... and a mapping of those constraints to variable type for the lhs.

        >>> print(simple_market.constraint_to_variable_map['unit_level']['ramp_down'])
           constraint_id unit service  coefficient
        0              0    A  energy          1.0
        1              1    B  energy          1.0

        Parameters
        ----------
        unit_limits : pd.DataFrame
            Capacity by unit.

            ==============  =====================================================================================
            Columns:        Description:
            unit            unique identifier of a dispatch unit (as `str`)
            initial_output  the output of the unit at the start of the dispatch interval, in MW (as `np.float64`)
            ramp_up_rate    the maximum rate at which the unit can increase output, in MW/h (as `np.float64`).
            ==============  =====================================================================================

        Returns
        -------
        None

        Raises
        ------
            ModelBuildError
                If the volume bids have not been set yet.
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If the column 'units', 'initial_output' or 'ramp_down_rate' is missing.
            UnexpectedColumn
                There is a column that is not 'units', 'initial_output' or 'ramp_down_rate'.
            ColumnValues
                If there are inf, null or negative values in the bid band columns.
        """
        # 1. Create the constraints
        rhs_and_type, variable_map = unit_constraints.ramp_down(unit_limits, self.next_constraint_id,
                                                                self.dispatch_interval)
        # 2. Save constraint details.
        self.constraints_rhs_and_type['ramp_down'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['ramp_down'] = variable_map
        # 3. Update the constraint and variable id counter
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('demand', ['region', 'demand'])
    @check.allowed_columns('demand', ['region', 'demand'])
    @check.repeated_rows('demand', ['region'])
    @check.column_data_types('demand', {'region': str, 'else': np.float64})
    @check.column_values_must_be_real('demand', ['demand'])
    @check.column_values_not_negative('demand', ['demand'])
    def set_demand_constraints(self, demand):
        """Creates constraints that force supply to equal to demand.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define a demand level in each region.

        >>> demand = pd.DataFrame({
        ...     'region': ['NSW'],
        ...     'demand': [100.0]})

        Create constraints.

        >>> simple_market.set_demand_constraints(demand)

        The market should now have a set of constraints.

        >>> print(simple_market.market_constraints_rhs_and_type['demand'])
          region  constraint_id type    rhs
        0    NSW              0    =  100.0

        ... and a mapping of those constraints to variable type for the lhs.

        >>> print(simple_market.constraint_to_variable_map['regional']['demand'])
           constraint_id region service  coefficient
        0              0    NSW  energy          1.0

        Parameters
        ----------
        demand : pd.DataFrame
            Demand by region.

            ========  =====================================================================================
            Columns:  Description:
            region    unique identifier of a region (as `str`)
            demand    the non dispatchable demand, in MW (as `np.float64`)
            ========  =====================================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the column 'region' or 'demand' is missing.
            UnexpectedColumn
                There is a column that is not 'region' or 'demand'.
            ColumnValues
                If there are inf, null or negative values in the volume column.
        """
        # 1. Create the constraints
        rhs_and_type, variable_map = market_constraints.energy(demand, self.next_constraint_id)
        # 2. Save constraint details
        self.market_constraints_rhs_and_type['demand'] = rhs_and_type
        self.constraint_to_variable_map['regional']['demand'] = variable_map
        # 3. Update the constraint id
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('fcas_requirements', ['set', 'service', 'region', 'volume'])
    @check.allowed_columns('fcas_requirements', ['set', 'service', 'region', 'volume', 'type'])
    @check.repeated_rows('fcas_requirements', ['set', 'service', 'region'])
    @check.column_data_types('fcas_requirements', {'set': str, 'service': str, 'region': str, 'type': str,
                                                   'else': np.float64})
    @check.column_values_must_be_real('fcas_requirements', ['volume'])
    @check.column_values_not_negative('fcas_requirements', ['volume'])
    def set_fcas_requirements_constraints(self, fcas_requirements):
        """Creates constraints that force FCAS supply to equal requirements.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define a regulation raise FCAS requirement that apply to all mainland states.

        >>> fcas_requirements = pd.DataFrame({
        ...     'set': ['raise_reg_main', 'raise_reg_main', 'raise_reg_main', 'raise_reg_main'],
        ...     'service': ['raise_reg', 'raise_reg', 'raise_reg', 'raise_reg'],
        ...     'region': ['QLD', 'NSW', 'VIC', 'SA'],
        ...     'volume': [100.0, 100.0, 100.0, 100.0]})

        Create constraints.

        >>> simple_market.set_fcas_requirements_constraints(fcas_requirements)

        The market should now have a set of constraints.

        >>> print(simple_market.market_constraints_rhs_and_type['fcas'])
                      set  constraint_id type    rhs
        0  raise_reg_main              0    =  100.0

        ... and a mapping of those constraints to variable type for the lhs.

        >>> print(simple_market.constraint_to_variable_map['regional']['fcas'])
           constraint_id    service region  coefficient
        0              0  raise_reg    QLD          1.0
        1              0  raise_reg    NSW          1.0
        2              0  raise_reg    VIC          1.0
        3              0  raise_reg     SA          1.0

        Parameters
        ----------
        fcas_requirements : pd.DataFrame
            requirement by set and the regions and service the requirement applies to.

            ========  ===================================================================
            Columns:  Description:
            set       unique identifier of the requirement set (as `str`)
            service   the service or services the requirement set applies to (as `str`)
            region    unique identifier of a region (as `str`)
            volume    the amount of service required, in MW (as `np.float64`)
            type      the direction of the constrain '=', '>=' or '<=', optional, a \n
                      value of '=' is assumed if the column is missing (as `str`)
            ========  ===================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any set and region combination.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the column 'set', 'service', 'region', or 'volume' is missing.
            UnexpectedColumn
                There is a column that is not 'set', 'service', 'region', 'volume' or 'type'.
            ColumnValues
                If there are inf, null or negative values in the volume column.
        """
        # 1. Create the constraints
        rhs_and_type, variable_map = market_constraints.fcas(fcas_requirements, self.next_constraint_id)
        # 2. Save constraint details
        self.market_constraints_rhs_and_type['fcas'] = rhs_and_type
        self.constraint_to_variable_map['regional']['fcas'] = variable_map
        # 3. Update the constraint id
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('fcas_max_availability', ['unit', 'service', 'max_availability'], arg=1)
    @check.allowed_columns('fcas_max_availability', ['unit', 'service', 'max_availability'], arg=1)
    @check.repeated_rows('fcas_max_availability', ['unit', 'service'], arg=1)
    @check.column_data_types('fcas_max_availability', {'unit': str, 'service': str, 'else': np.float64}, arg=1)
    @check.column_values_must_be_real('fcas_max_availability', ['max_availability'], arg=1)
    @check.column_values_not_negative('fcas_max_availability', ['max_availability'], arg=1)
    def set_fcas_max_availability(self, fcas_max_availability):
        """Creates constraints to ensure fcas dispatch is limited to the availability specified in the FCAS trapezium.

        The constraints are described in the
        :download:`FCAS MODEL IN NEMDE documentation section 2  <../../docs/pdfs/FCAS Model in NEMDE.pdf>`.

        Examples
        --------

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot(dispatch_interval=60)

        Define the FCAS max_availability.

        >>> fcas_max_availability = pd.DataFrame({
        ... 'unit': ['A'],
        ... 'service': ['raise_6s'],
        ... 'max_availability': [60.0]})

        Set the joint availability constraints.

        >>> simple_market.set_fcas_max_availability(fcas_max_availability)

        TNow the market should have the constraints and their mapping to decision varibales.

        >>> print(simple_market.constraints_rhs_and_type['fcas_max_availability'])
          unit   service  constraint_id type   rhs
        0    A  raise_6s              0   <=  60.0

        >>> print(simple_market.constraint_to_variable_map['unit_level']['fcas_max_availability'])
           constraint_id unit   service  coefficient
        0              0    A  raise_6s          1.0

        Parameters
        ----------
        fcas_max_availability : pd.DataFrame
            The FCAS max_availability for the services being offered.

            ================   ======================================================================
            Columns:           Description:
            unit               unique identifier of a dispatch unit (as `str`)
            service            the contingency service being offered (as `str`)
            max_availability   the maximum volume of the contingency service in MW (as `np.float64`)
            ================   ======================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit and service combination in contingency_trapeziums.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the columns 'unit', 'service' or 'max_availability' is missing from fcas_max_availability.
            UnexpectedColumn
                If there are columns other than 'unit', 'service' or 'max_availability' in fcas_max_availability.
            ColumnValues
                If there are inf, null or negative values in the columns of type `np.float64`.
        """

        rhs_and_type, variable_map = unit_constraints.fcas_max_availability(fcas_max_availability,
                                                                            self.next_constraint_id)

        self.constraints_rhs_and_type['fcas_max_availability'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['fcas_max_availability'] = variable_map
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('regulation_units', ['unit', 'service'], arg=1)
    @check.allowed_columns('regulation_units', ['unit', 'service'], arg=1)
    @check.repeated_rows('regulation_units', ['unit', 'service'], arg=1)
    @check.column_data_types('regulation_units', {'unit': str, 'service': str}, arg=1)
    @check.required_columns('unit_limits', ['unit', 'initial_output', 'ramp_up_rate', 'ramp_down_rate'], arg=2)
    @check.allowed_columns('unit_limits', ['unit', 'initial_output', 'ramp_up_rate', 'ramp_down_rate'], arg=2)
    @check.repeated_rows('unit_limits', ['unit'], arg=2)
    @check.column_data_types('unit_limits', {'unit': str, 'else': np.float64}, arg=2)
    @check.column_values_must_be_real('unit_limits', ['initial_output', 'ramp_up_rate', 'ramp_down_rate'], arg=2)
    @check.column_values_not_negative('unit_limits', ['ramp_up_rate', 'ramp_down_rate'], arg=2)
    def set_joint_ramping_constraints(self, regulation_units, unit_limits):
        """Create constraints that ensure the provision of energy and fcas are within unit ramping capabilities.

        The constraints are described in the
        :download:`FCAS MODEL IN NEMDE documentation section 6.1  <../../docs/pdfs/FCAS Model in NEMDE.pdf>`.

        On a unit basis they take the form of:

            Energy dispatch + Regulation raise target <= initial output + ramp up rate / (dispatch interval / 60)

        and

            Energy dispatch + Regulation lower target <= initial output - ramp down rate / (dispatch interval / 60)

        Examples
        --------

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot(dispatch_interval=60)

        Define the set of units providing regulation services.

        >>> regulation_units = pd.DataFrame({
        ...   'unit': ['A', 'B', 'B'],
        ...   'service': ['raise_reg', 'lower_reg', 'raise_reg']})

        Define unit initial outputs and ramping capabilities.

        >>> unit_limits = pd.DataFrame({
        ...   'unit': ['A', 'B'],
        ...   'initial_output': [100.0, 80.0],
        ...   'ramp_up_rate': [20.0, 10.0],
        ...   'ramp_down_rate': [15.0, 25.0]})

        Create the joint ramping constraints.

        >>> simple_market.set_joint_ramping_constraints(regulation_units, unit_limits)

        Now the market should have the constraints and their mapping to decision varibales.

        >>> print(simple_market.constraints_rhs_and_type['joint_ramping'])
          unit  constraint_id type    rhs
        0    A              0   <=  120.0
        1    B              1   >=   55.0
        2    B              2   <=   90.0

        >>> print(simple_market.constraint_to_variable_map['unit_level']['joint_ramping'])
           constraint_id unit    service  coefficient
        0              0    A  raise_reg          1.0
        1              1    B  lower_reg         -1.0
        2              2    B  raise_reg          1.0
        0              0    A     energy          1.0
        1              1    B     energy          1.0
        2              2    B     energy          1.0

        Parameters
        ----------
        regulation_units : pd.DataFrame
            The units with bids submitted to provide regulation FCAS

            ========  =======================================================================
            Columns:  Description:
            unit      unique identifier of a dispatch unit (as `str`)
            service   the regulation service being bid for raise_reg or lower_reg  (as `str`)
            ========  =======================================================================

        unit_limits : pd.DataFrame
            The initial output and ramp rates of units

            ==============  =====================================================================================
            Columns:        Description:
            unit            unique identifier of a dispatch unit (as `str`)
            initial_output  the output of the unit at the start of the dispatch interval, in MW (as `np.float64`)
            ramp_up_rate    the maximum rate at which the unit can increase output, in MW/h (as `np.float64`)
            ramp_down_rate  the maximum rate at which the unit can decrease output, in MW/h (as `np.float64`)
            ==============  =====================================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit and service combination in regulation_units, or if there is
                more than one row for any unit in unit_limits.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the columns 'unit' or 'service' are missing from regulations_units, or if the columns 'unit',
                'initial_output', 'ramp_up_rate' or 'ramp_down_rate' are missing from unit_limits.
            UnexpectedColumn
                If there are columns other than 'unit' or 'service' in regulations_units, or if there are columns other
                than 'unit', 'initial_output', 'ramp_up_rate' or 'ramp_down_rate' in unit_limits.
            ColumnValues
                If there are inf, null or negative values in the columns of type `np.float64`.
        """

        rhs_and_type, variable_map = fcas_constraints.joint_ramping_constraints(
            regulation_units, unit_limits, self.unit_info.loc[:, ['unit', 'dispatch_type']], self.dispatch_interval,
            self.next_constraint_id)

        self.constraints_rhs_and_type['joint_ramping'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['joint_ramping'] = variable_map
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('contingency_trapeziums', ['unit', 'service', 'max_availability', 'enablement_min',
                                                       'low_break_point', 'high_break_point', 'enablement_max'], arg=1)
    @check.allowed_columns('contingency_trapeziums', ['unit', 'service', 'max_availability', 'enablement_min',
                                                      'low_break_point', 'high_break_point', 'enablement_max'], arg=1)
    @check.repeated_rows('contingency_trapeziums', ['unit', 'service'], arg=1)
    @check.column_data_types('contingency_trapeziums', {'unit': str, 'service': str, 'else': np.float64}, arg=1)
    @check.column_values_must_be_real('contingency_trapeziums', ['max_availability', 'enablement_min',
                                                                 'low_break_point', 'high_break_point',
                                                                 'enablement_max'], arg=1)
    @check.column_values_not_negative('contingency_trapeziums', ['max_availability', 'enablement_min',
                                                                 'low_break_point', 'enablement_max'], arg=1)
    def set_joint_capacity_constraints(self, contingency_trapeziums):
        """Creates constraints to ensure there is adequate capacity for contingency, regulation and energy dispatch.

        Create two constraints for each contingency services, one ensures operation on upper slope of the fcas
        contingency trapezium is consistent with regulation raise and energy dispatch, the second ensures operation on
        upper slope of the fcas contingency trapezium is consistent with regulation lower and energy dispatch.

        The constraints are described in the
        :download:`FCAS MODEL IN NEMDE documentation section 6.2  <../../docs/pdfs/FCAS Model in NEMDE.pdf>`.

        Examples
        --------

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot(dispatch_interval=60)

        Define the FCAS contingency trapeziums.

        >>> contingency_trapeziums = pd.DataFrame({
        ... 'unit': ['A'],
        ... 'service': ['raise_6s'],
        ... 'max_availability': [60.0],
        ... 'enablement_min': [20.0],
        ... 'low_break_point': [40.0],
        ... 'high_break_point': [60.0],
        ... 'enablement_max': [80.0]})

        Set the joint capacity constraints.

        >>> simple_market.set_joint_capacity_constraints(contingency_trapeziums)

        TNow the market should have the constraints and their mapping to decision varibales.

        >>> print(simple_market.constraints_rhs_and_type['joint_capacity'])
          unit   service  constraint_id type   rhs
        0    A  raise_6s              0   <=  80.0
        0    A  raise_6s              1   >=  20.0

        >>> print(simple_market.constraint_to_variable_map['unit_level']['joint_capacity'])
           constraint_id unit    service  coefficient
        0              0    A     energy     1.000000
        0              0    A   raise_6s     0.333333
        0              0    A  raise_reg     1.000000
        0              1    A     energy     1.000000
        0              1    A   raise_6s    -0.333333
        0              1    A  lower_reg    -1.000000

        Parameters
        ----------
        contingency_trapeziums : pd.DataFrame
            The FCAS trapeziums for the contingency services being offered.

            ================   ======================================================================
            Columns:           Description:
            unit               unique identifier of a dispatch unit (as `str`)
            service            the contingency service being offered (as `str`)
            max_availability   the maximum volume of the contingency service in MW (as `np.float64`)
            enablement_min     the energy dispatch level at which the unit can begin to provide the
                               contingency service, in MW (as `np.float64`)
            low_break_point    the energy dispatch level at which the unit can provide the full
                               contingency service offered, in MW (as `np.float64`)
            high_break_point   the energy dispatch level at which the unit can no longer provide the
                               full contingency service offered, in MW (as `np.float64`)
            enablement_max     the energy dispatch level at which the unit can no longer begin
                               the contingency service, in MW (as `np.float64`)
            ================   ======================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit and service combination in contingency_trapeziums.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the columns 'unit', 'service', 'max_availability', 'enablement_min', 'low_break_point',
                'high_break_point' or 'enablement_max' from contingency_trapeziums.
            UnexpectedColumn
                If there are columns other than 'unit', 'service', 'max_availability', 'enablement_min',
                'low_break_point', 'high_break_point' or 'enablement_max' in contingency_trapeziums.
            ColumnValues
                If there are inf, null or negative values in the columns of type `np.float64`.
        """

        rhs_and_type, variable_map = fcas_constraints.joint_capacity_constraints(
            contingency_trapeziums, self.unit_info.loc[:, ['unit', 'dispatch_type']], self.next_constraint_id)
        self.constraints_rhs_and_type['joint_capacity'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['joint_capacity'] = variable_map
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('regulation_trapeziums', ['unit', 'service', 'max_availability', 'enablement_min',
                                                      'low_break_point', 'high_break_point', 'enablement_max'], arg=1)
    @check.allowed_columns('regulation_trapeziums', ['unit', 'service', 'max_availability', 'enablement_min',
                                                     'low_break_point', 'high_break_point', 'enablement_max'], arg=1)
    @check.repeated_rows('regulation_trapeziums', ['unit', 'service'], arg=1)
    @check.column_data_types('regulation_trapeziums', {'unit': str, 'service': str, 'else': np.float64}, arg=1)
    @check.column_values_must_be_real('regulation_trapeziums', ['max_availability', 'enablement_min',
                                                                'low_break_point', 'high_break_point',
                                                                'enablement_max'], arg=1)
    @check.column_values_not_negative('regulation_trapeziums', ['max_availability', 'enablement_min',
                                                                'low_break_point', 'enablement_max'], arg=1)
    def set_energy_and_regulation_capacity_constraints(self, regulation_trapeziums):
        """Creates constraints to ensure there is adequate capacity for regulation and energy dispatch targets.

        Create two constraints for each regulation services, one ensures operation on upper slope of the fcas
        regulation trapezium is consistent with energy dispatch, the second ensures operation on lower slope of the
        fcas regulation trapezium is consistent with energy dispatch.

        The constraints are described in the
        :download:`FCAS MODEL IN NEMDE documentation section 6.3  <../../docs/pdfs/FCAS Model in NEMDE.pdf>`.

        Examples
        --------

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot(dispatch_interval=60)

        Define the FCAS regulation trapeziums.

        >>> regulation_trapeziums = pd.DataFrame({
        ... 'unit': ['A'],
        ... 'service': ['raise_reg'],
        ... 'max_availability': [60.0],
        ... 'enablement_min': [20.0],
        ... 'low_break_point': [40.0],
        ... 'high_break_point': [60.0],
        ... 'enablement_max': [80.0]})

        Set the joint capacity constraints.

        >>> simple_market.set_energy_and_regulation_capacity_constraints(regulation_trapeziums)

        TNow the market should have the constraints and their mapping to decision varibales.

        >>> print(simple_market.constraints_rhs_and_type['energy_and_regulation_capacity'])
          unit    service  constraint_id type   rhs
        0    A  raise_reg              0   <=  80.0
        0    A  raise_reg              1   >=  20.0

        >>> print(simple_market.constraint_to_variable_map['unit_level']['energy_and_regulation_capacity'])
           constraint_id unit    service  coefficient
        0              0    A     energy     1.000000
        0              0    A  raise_reg     0.333333
        0              1    A     energy     1.000000
        0              1    A  raise_reg    -0.333333

        Parameters
        ----------
        regulation_trapeziums : pd.DataFrame
            The FCAS trapeziums for the regulation services being offered.

            ================   ======================================================================
            Columns:           Description:
            unit               unique identifier of a dispatch unit (as `str`)
            service            the regulation service being offered (as `str`)
            max_availability   the maximum volume of the contingency service in MW (as `np.float64`)
            enablement_min     the energy dispatch level at which the unit can begin to provide
                               the contingency service, in MW (as `np.float64`)
            low_break_point    the energy dispatch level at which the unit can provide the full
                               contingency service offered, in MW (as `np.float64`)
            high_break_point   the energy dispatch level at which the unit can no longer provide the
                               full contingency service offered, in MW (as `np.float64`)
            enablement_max     the energy dispatch level at which the unit can no longer provide any
                               contingency service, in MW (as `np.float64`)
            ================   ======================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit and service combination in regulation_trapeziums.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the columns 'unit', 'service', 'max_availability', 'enablement_min', 'low_break_point',
                'high_break_point' or 'enablement_max' from regulation_trapeziums.
            UnexpectedColumn
                If there are columns other than 'unit', 'service', 'max_availability', 'enablement_min',
                'low_break_point', 'high_break_point' or 'enablement_max' in regulation_trapeziums.
            ColumnValues
                If there are inf, null or negative values in the columns of type `np.float64`.
        """

        rhs_and_type, variable_map = \
            fcas_constraints.energy_and_regulation_capacity_constraints(regulation_trapeziums, self.next_constraint_id)
        self.constraints_rhs_and_type['energy_and_regulation_capacity'] = rhs_and_type
        self.constraint_to_variable_map['unit_level']['energy_and_regulation_capacity'] = variable_map
        self.next_constraint_id = max(rhs_and_type['constraint_id']) + 1

    @check.required_columns('interconnector_directions_and_limits',
                            ['interconnector', 'to_region', 'from_region', 'max', 'min'])
    @check.allowed_columns('interconnector_directions_and_limits',
                           ['interconnector', 'to_region', 'from_region', 'max', 'min', 'from_region_loss_factor',
                            'to_region_loss_factor'])
    @check.repeated_rows('interconnector_directions_and_limits', ['interconnector'])
    @check.column_data_types('interconnector_directions_and_limits',
                             {'interconnector': str, 'to_region': str, 'from_region': str, 'else': np.float64})
    @check.column_values_must_be_real('interconnector_directions_and_limits', ['min', 'max', 'from_region_loss_factor',
                                                                               'to_region_loss_factor'])
    def set_interconnectors(self, interconnector_directions_and_limits):
        """Create lossless links between specified regions.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define a an interconnector between NSW and VIC so generator can A can be used to meet demand in VIC.

        >>> interconnector = pd.DataFrame({
        ...     'interconnector': ['inter_one'],
        ...     'to_region': ['VIC'],
        ...     'from_region': ['NSW'],
        ...     'max': [100.0],
        ...     'min': [-100.0]})

        Create the interconnector.

        >>> simple_market.set_interconnectors(interconnector)

        The market should now have a decision variable defined for each interconnector.

        >>> print(simple_market.decision_variables['interconnectors'])
          interconnector  variable_id  lower_bound  upper_bound        type
        0      inter_one            0       -100.0        100.0  continuous

        ... and a mapping of those variables to to regional energy constraints.

        >>> print(simple_market.variable_to_constraint_map['regional']['interconnectors'])
           variable_id region service  coefficient
        0            0    VIC  energy          1.0
        1            0    NSW  energy         -1.0

        Parameters
        ----------
        interconnector_directions_and_limits : pd.DataFrame
            Interconnector definition.

            ========================  ==================================================================================
            Columns:                  Description:
            interconnector            unique identifier of a interconnector (as `str`)
            to_region                 the region that receives power when flow is in the positive direction (as `str`)
            from_region               the region that power is drawn from when flow is in the positive direction
                                      (as `str`)
            max                       the maximum power flow in the positive direction, in MW (as `np.float64`)
            min                       the maximum power flow in the negative direction, in MW (as `np.float64`)
            from_region_loss_factor   the loss factor at the from region end of the interconnector, refers the the from
                                      region end to the regional reference node, optional, assumed to equal 1.0, i.e. that
                                      the from end is at the regional reference node if the column is not provided
                                      (as `np.float`)
            to_region_loss_factor     the loss factor at the to region end of the interconnector, refers the the to
                                      region end to the regional reference node, optional, assumed equal to 1.0, i.e. that
                                      the to end is at the regional reference node if the column is not provided
                                      (as `np.float`)
            ========================  ==================================================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any interconnector.
            ColumnDataTypeError
                If columns are not of the require type.
            MissingColumnError
                If any columns are missing.
            UnexpectedColumn
                If there are any additional columns in the input DataFrame.
            ColumnValues
                If there are inf, null values in the max and min columns.
        """
        if 'from_region_loss_factor' not in interconnector_directions_and_limits.columns:
            interconnector_directions_and_limits['from_region_loss_factor'] = 1.0
        if 'to_region_loss_factor' not in interconnector_directions_and_limits.columns:
            interconnector_directions_and_limits['to_region_loss_factor'] = 1.0

        self.interconnector_directions = \
            interconnector_directions_and_limits.loc[:, ['interconnector', 'to_region', 'from_region',
                                                         'from_region_loss_factor', 'to_region_loss_factor']]
        # Create unit variable ids and map variables to regional constraints
        self.decision_variables['interconnectors'], self.variable_to_constraint_map['regional']['interconnectors'] \
            = inter.create(interconnector_directions_and_limits, self.next_variable_id)

        self.next_variable_id = max(self.decision_variables['interconnectors']['variable_id']) + 1

    @check.interconnectors_exist
    @check.required_columns('loss_functions', ['interconnector', 'from_region_loss_share', 'loss_function'], arg=1)
    @check.allowed_columns('loss_functions', ['interconnector', 'from_region_loss_share', 'loss_function'], arg=1)
    @check.repeated_rows('loss_functions', ['interconnector'], arg=1)
    @check.column_data_types('loss_functions', {'interconnector': str, 'from_region_loss_share': np.float64,
                                                'loss_function': 'callable'}, arg=1)
    @check.column_values_must_be_real('loss_functions', ['break_point'], arg=1)
    @check.column_values_outside_range('loss_functions', {'from_region_loss_share': [0.0, 1.0]}, arg=1)
    @check.required_columns('interpolation_break_point', ['interconnector', 'loss_segment', 'break_point'], arg=2)
    @check.allowed_columns('interpolation_break_point', ['interconnector', 'loss_segment', 'break_point'], arg=2)
    @check.repeated_rows('interpolation_break_point', ['interconnector', 'loss_segment', 'break_point'], arg=2)
    @check.column_data_types('interpolation_break_point', {'interconnector': str, 'loss_segment': np.int64,
                                                           'break_point': np.float64}, arg=2)
    @check.column_values_must_be_real('interpolation_break_point', ['break_point'], arg=2)
    def set_interconnector_losses(self, loss_functions, interpolation_break_points):
        """Creates linearised loss functions for interconnectors.

        Creates a loss variable for each interconnector, this variable models losses by adding demand to each region.
        The losses are proportioned to each region according to the from_region_loss_share. In a region with one
        interconnector, where the region is the nominal from region, the impact on the demand constraint would be:

            generation - interconnector flow - interconnector losses * from_region_loss_share = demand

        If the region was the nominal to region, then:

            generation + interconnector flow - interconnector losses *  (1 - from_region_loss_share) = demand

        The loss variable is constrained to be a linear interpolation of the loss function between the two break points
        either side of to the actual line flow. This is achieved using a type 2 Special ordered set, where each
        variable is bound between 0 and 1, only 2 variables can be greater than 0 and all variables must sum to 1.
        The actual loss function is evaluated at each break point, the variables of the special order set are
        constrained such that their values weight the distance of the actual flow from the break points on either side
        e.g. If we had 3 break points at -100 MW, 0 MW and 100 MW, three weight variables w1, w2, and w3,
        and a loss function f, then the constraints would be of the form.

        Constrain the weight variables to sum to one:

            w1 + w2 + w3 = 1

        Constrain the weight variables give the relative weighting of adjacent breakpoint:

            w1 * -100.0 + w2 * 0.0 + w3 * 100.0 = interconnector flow

        Constrain the interconnector losses to be the weighted sum of the losses at the adjacent break point:

            w1 * f(-100.0) + w2 * f(0.0) + w3 * f(100.0) = interconnector losses

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        >>> import pandas as pd
        >>> from nempy import markets

        Create a market instance.

        >>> simple_market = markets.Spot()

        Create the interconnector, this need to be done before a interconnector losses can be set.

        >>> interconnectors = pd.DataFrame({
        ...    'interconnector': ['little_link'],
        ...    'to_region': ['VIC'],
        ...    'from_region': ['NSW'],
        ...    'max': [100.0],
        ...    'min': [-120.0]})

        >>> simple_market.set_interconnectors(interconnectors)

        Define the interconnector loss function. In this case losses are always 5 % of line flow.

        >>> def constant_losses(flow=None):
        ...     return abs(flow) * 0.05

        Define the function on a per interconnector basis. Also details how the losses should be proportioned to the
        connected regions.

        >>> loss_functions = pd.DataFrame({
        ...    'interconnector': ['little_link'],
        ...    'from_region_loss_share': [0.5],  # losses are shared equally.
        ...    'loss_function': [constant_losses]})

        Define The points to linearly interpolate the loss function between. In this example the loss function is
        linear so only three points are needed, but if a non linear loss function was used then more points would
        result in a better approximation.

        >>> interpolation_break_points = pd.DataFrame({
        ...    'interconnector': ['little_link', 'little_link', 'little_link'],
        ...    'loss_segment': [1, 2, 3],
        ...    'break_point': [-120.0, 0.0, 100]})

        >>> simple_market.set_interconnector_losses(loss_functions, interpolation_break_points)

        The market should now have a decision variable defined for each interconnector's losses.

        >>> print(simple_market.decision_variables['interconnector_losses'])
          interconnector  variable_id  lower_bound  upper_bound        type
        0    little_link            1       -120.0        120.0  continuous

        ... and a mapping of those variables to regional energy constraints.

        >>> print(simple_market.variable_to_constraint_map['regional']['interconnector_losses'])
           variable_id region service  coefficient
        0            1    VIC  energy         -0.5
        1            1    NSW  energy         -0.5

        The market will also have a special ordered set of weight variables for interpolating the loss function
        between the break points.

        >>> print(simple_market.decision_variables['interpolation_weights'].loc[:,
        ...       ['interconnector', 'loss_segment', 'break_point', 'variable_id']])
          interconnector  loss_segment  break_point  variable_id
        0    little_link             1       -120.0            2
        1    little_link             2          0.0            3
        2    little_link             3        100.0            4

        >>> print(simple_market.decision_variables['interpolation_weights'].loc[:,
        ...       ['variable_id', 'lower_bound', 'upper_bound', 'type']])
           variable_id  lower_bound  upper_bound        type
        0            2          0.0          1.0  continuous
        1            3          0.0          1.0  continuous
        2            4          0.0          1.0  continuous

        and a set of constraints that implement the interpolation, see above explanation.

        >>> print(simple_market.constraints_rhs_and_type['interpolation_weights'])
          interconnector  constraint_id type  rhs
        0    little_link              0    =  1.0

        >>> print(simple_market.constraints_dynamic_rhs_and_type['link_loss_to_flow'])
          interconnector  constraint_id type  rhs_variable_id
        0    little_link              1    =                0
        0    little_link              2    =                1

        >>> print(simple_market.lhs_coefficients['interconnector_losses'])
           variable_id  constraint_id  coefficient
        0            2              0          1.0
        1            3              0          1.0
        2            4              0          1.0
        0            2              1       -120.0
        1            3              1          0.0
        2            4              1        100.0
        0            2              2          6.0
        1            3              2          0.0
        2            4              2          5.0


        Parameters
        ----------
        loss_functions : pd.DataFrame

            ======================  ==============================================================================
            Columns:                Description:
            interconnector          unique identifier of a interconnector (as `str`)
            from_region_loss_share  The fraction of loss occuring in the from region, 0.0 to 1.0 (as `np.float64`)
            loss_function           A function that takes a flow, in MW as a float and returns the losses in MW
                                    (as `callable`)
            ======================  ==============================================================================

        interpolation_break_points : pd.DataFrame

            ==============  ============================================================================================
            Columns:        Description:
            interconnector  unique identifier of a interconnector (as `str`)
            loss_segment    unique identifier of a loss segment on an interconnector basis (as `np.float64`)
            break_point     points between which the loss function will be linearly interpolated, in MW
                            (as `np.float64`)
            ==============  ============================================================================================

        Returns
        -------
        None

        Raises
        ------
            ModelBuildError
                If all the interconnectors in the input data have not already been added to the model.
            RepeatedRowError
                If there is more than one row for any interconnector in loss_functions. Or if there is a repeated break
                point for an interconnector in interpolation_break_points.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If any columns are missing.
            UnexpectedColumn
                If there are any additional columns in the input DataFrames.
            ColumnValues
                If there are inf or null values in the numeric columns of either input DataFrames. Or if
                from_region_loss_share are outside the range of 0.0 to 1.0
        """
        self.interconnector_loss_shares = loss_functions.loc[:, ['interconnector', 'from_region_loss_share']]

        # Create loss variables.
        loss_variables, loss_variables_constraint_map = \
            inter.create_loss_variables(self.decision_variables['interconnectors'],
                                        self.variable_to_constraint_map['regional']['interconnectors'],
                                        loss_functions, self.next_variable_id)
        next_variable_id = loss_variables['variable_id'].max() + 1

        # Create weight variables.
        weight_variables = inter.create_weights(interpolation_break_points, next_variable_id)

        next_variable_id = weight_variables['variable_id'].max() + 1

        # Creates weights sum constraint.
        weights_sum_lhs, weights_sum_rhs = inter.create_weights_must_sum_to_one(weight_variables,
                                                                                self.next_constraint_id)
        next_constraint_id = weights_sum_rhs['constraint_id'].max() + 1

        # Link weights to interconnector flow.
        link_to_flow_lhs, link_to_flow_rhs = inter.link_weights_to_inter_flow(weight_variables,
                                                                              self.decision_variables[
                                                                                  'interconnectors'],
                                                                              next_constraint_id)
        next_constraint_id = link_to_flow_rhs['constraint_id'].max() + 1

        # Link the losses to the interpolation weights.
        link_to_loss_lhs, link_to_loss_rhs = \
            inter.link_inter_loss_to_interpolation_weights(weight_variables, loss_variables, loss_functions,
                                                           next_constraint_id)

        # Combine lhs sides, note these are complete lhs and don't need to be mapped to constraints.
        lhs = pd.concat([weights_sum_lhs, link_to_flow_lhs, link_to_loss_lhs])

        # Combine constraints with a dynamic rhs i.e. a variable on the rhs.
        dynamic_rhs = pd.concat([link_to_flow_rhs, link_to_loss_rhs])

        # Save results.
        self.decision_variables['interconnector_losses'] = loss_variables
        self.variable_to_constraint_map['regional']['interconnector_losses'] = loss_variables_constraint_map
        self.decision_variables['interpolation_weights'] = weight_variables
        self.lhs_coefficients['interconnector_losses'] = lhs
        self.constraints_rhs_and_type['interpolation_weights'] = weights_sum_rhs
        self.constraints_dynamic_rhs_and_type['link_loss_to_flow'] = dynamic_rhs
        self.next_variable_id = pd.concat([loss_variables, weight_variables])['variable_id'].max() + 1
        self.next_constraint_id = pd.concat([weights_sum_rhs, dynamic_rhs])['constraint_id'].max() + 1

    @check.required_columns('generic_constraint_parameters', ['set', 'type', 'rhs'])
    @check.allowed_columns('generic_constraint_parameters', ['set', 'type', 'rhs'])
    @check.repeated_rows('generic_constraint_parameters', ['set'])
    @check.column_data_types('generic_constraint_parameters', {'set': str, 'type': str, 'rhs': np.float64})
    @check.column_values_must_be_real('generic_constraint_parameters', ['rhs'])
    def set_generic_constraints(self, generic_constraint_parameters):
        """Creates a set of generic constraints, adding the constraint type, rhs.

        This sets a set of arbitrary constraints, but only the type and rhs values. The lhs terms can be added to these
        constraints using the methods link_units_to_generic_constraints, link_interconnectors_to_generic_constraints
        and link_regions_to_generic_constraints.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        >>> import pandas as pd
        >>> from nempy import markets

        Create a market instance.

        >>> market = markets.Spot()

        Define a set of generic constraints and add them to the market.

        >>> generic_constraint_parameters = pd.DataFrame({
        ...   'set': ['A', 'B'],
        ...   'type': ['>=', '<='],
        ...   'rhs': [10.0, -100.0]})

        >>> market.set_generic_constraints(generic_constraint_parameters)

        Now the market should have a set of generic constraints.

        >>> print(market.constraints_rhs_and_type['generic'])
          set  constraint_id type    rhs
        0   A              0   >=   10.0
        1   B              1   <= -100.0

        Parameters
        ----------
        generic_constraint_parameters : pd.DataFrame

            =============  ==============================================================
            Columns:       Description:
            set            the unique identifier of the constraint set (as `str`)
            type           the direction of the constraint >=, <= or = (as `str`)
            rhs            the right hand side value of the constraint (as `np.float64`)
            =============  ==============================================================

        Returns
        -------
        None

        Raises
        ------
            RepeatedRowError
                If there is more than one row for any unit.
            ColumnDataTypeError
                If columns are not of the required type.
            MissingColumnError
                If the column 'set', 'type' or 'rhs' is missing.
            UnexpectedColumn
                There is a column that is not 'set', 'type' or 'rhs' .
            ColumnValues
                If there are inf or null values in the rhs column.
        """
        type_and_rhs = hf.save_index(generic_constraint_parameters, 'constraint_id', self.next_constraint_id)
        # self.constraint_to_variable_map['unit_level']['generic'] = type_and_rhs.loc[:, ['set', 'constraint_id']]
        # self.constraint_to_variable_map['unit_level']['generic']['coefficient'] = 1.0
        self.constraints_rhs_and_type['generic'] = type_and_rhs.loc[:, ['set', 'constraint_id', 'type', 'rhs']]
        self.next_constraint_id = type_and_rhs['constraint_id'].max() + 1

    @check.required_columns('unit_coefficients', ['set', 'unit', 'service', 'coefficient'])
    @check.allowed_columns('unit_coefficients', ['set', 'unit', 'service', 'coefficient'])
    @check.repeated_rows('unit_coefficients', ['set', 'unit', 'service'])
    @check.column_data_types('unit_coefficients', {'set': str, 'unit': str, 'service': str, 'coefficient': np.float64})
    @check.column_values_must_be_real('unit_coefficients', ['coefficient'])
    def link_units_to_generic_constraints(self, unit_coefficients):
        """Set the lhs coefficients of generic constraints on unit basis.

        Notes
        -----
        These sets also maps to the sets in the fcas market constraints. One potential use of this is prevent specific
        units from helping to meet fcas constraints by giving them a negative one (-1.0) coefficient using this method
        for particular fcas markey constraints.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        >>> import pandas as pd
        >>> from nempy import markets

        Create a market instance.

        >>> market = markets.Spot()

        Define unit lhs coefficients for generic constraints.

        >>> unit_coefficients = pd.DataFrame({
        ...   'set': ['A', 'A', 'B'],
        ...   'unit': ['X', 'Y', 'X'],
        ...   'service': ['energy', 'energy', 'raise_reg'],
        ...   'coefficient': [1.0, 1.0, -1.0]})

        >>> market.link_units_to_generic_constraints(unit_coefficients)

        Note all this does is save this information to the market object, linking to specific variable ids and
        constraint id occurs when the dispatch method is called.

        >>> print(market.generic_constraint_lhs['units'])
          set unit    service  coefficient
        0   A    X     energy          1.0
        1   A    Y     energy          1.0
        2   B    X  raise_reg         -1.0

        Parameters
        ----------
        unit_coefficients : pd.DataFrame

            =============  ==============================================================
            Columns:       Description:
            set            the unique identifier of the constraint set to map the
                           lhs coefficients to (as `str`)
            unit           the unit whose variables will be mapped to the lhs (as `str`)
            service        the service whose variables will be mapped to the lhs (as `str`)
            coefficient    the lhs coefficient (as `np.float64`)
            =============  ==============================================================

        Raises
        ------
        RepeatedRowError
            If there is more than one row for any set, unit and service combination.
        ColumnDataTypeError
            If columns are not of the required type.
        MissingColumnError
            If the column 'set', 'unit', 'serice' or 'coefficient' is missing.
        UnexpectedColumn
            There is a column that is not 'set', 'unit', 'serice' or 'coefficient'.
        ColumnValues
            If there are inf or null values in the rhs coefficient.
        """
        self.generic_constraint_lhs['unit'] = unit_coefficients

    @check.required_columns('region_coefficients', ['set', 'region', 'service', 'coefficient'])
    @check.allowed_columns('region_coefficients', ['set', 'region', 'service', 'coefficient'])
    @check.repeated_rows('region_coefficients', ['set', 'region', 'service'])
    @check.column_data_types('region_coefficients', {'set': str, 'region': str, 'service': str,
                                                     'coefficient': np.float64})
    @check.column_values_must_be_real('region_coefficients', ['coefficient'])
    def link_regions_to_generic_constraints(self, region_coefficients):
        """Set the lhs coefficients of generic constraints on region basis.

        This effectively acts as short cut for mapping unit variables to a generic constraint. If a particular
        service in a particular region is included here then all units in this region will have their variables
        of this service included on the lhs of this constraint set.

        Notes
        -----
        These sets also map to the set in the fcas market constraints.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        >>> import pandas as pd
        >>> from nempy import markets

        Create a market instance.

        >>> market = markets.Spot()

        Define region lhs coefficients for generic constraints.

        >>> region_coefficients = pd.DataFrame({
        ...   'set': ['A', 'A', 'B'],
        ...   'region': ['X', 'Y', 'X'],
        ...   'service': ['energy', 'energy', 'raise_reg'],
        ...   'coefficient': [1.0, 1.0, -1.0]})

        >>> market.link_regions_to_generic_constraints(region_coefficients)

        Note all this does is save this information to the market object, linking to specific variable ids and
        constraint id occurs when the dispatch method is called.

        >>> print(market.generic_constraint_lhs['region'])
          set region    service  coefficient
        0   A      X     energy          1.0
        1   A      Y     energy          1.0
        2   B      X  raise_reg         -1.0

        Parameters
        ----------
        unit_coefficients : pd.DataFrame

            =============  ==============================================================
            Columns:       Description:
            set            the unique identifier of the constraint set to map the
                           lhs coefficients to (as `str`)
            region         the region whose variables will be mapped to the lhs (as `str`)
            service        the service whose variables will be mapped to the lhs (as `str`)
            coefficient    the lhs coefficient (as `np.float64`)
            =============  ==============================================================

        Raises
        ------
        RepeatedRowError
            If there is more than one row for any set, region and service combination.
        ColumnDataTypeError
            If columns are not of the required type.
        MissingColumnError
            If the column 'set', 'region', 'service' or 'coefficient' is missing.
        UnexpectedColumn
            There is a column that is not 'set', 'region', 'service' or 'coefficient'.
        ColumnValues
            If there are inf or null values in the rhs coefficient.
        """
        self.generic_constraint_lhs['region'] = region_coefficients

    @check.required_columns('interconnector_coefficients', ['set', 'interconnector', 'coefficient'])
    @check.allowed_columns('interconnector_coefficients', ['set', 'interconnector', 'coefficient'])
    @check.repeated_rows('interconnector_coefficients', ['set', 'interconnector'])
    @check.column_data_types('interconnector_coefficients', {'set': str, 'interconnector': str,
                                                             'coefficient': np.float64})
    @check.column_values_must_be_real('interconnector_coefficients', ['coefficient'])
    def link_interconnectors_to_generic_constraints(self, interconnector_coefficients):
        """Set the lhs coefficients of generic constraints on interconnector basis.

        Notes
        -----
        These sets also map to the set in the fcas market constraints.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        >>> import pandas as pd
        >>> from nempy import markets

        Create a market instance.

        >>> market = markets.Spot()

        Define region lhs coefficients for generic constraints. All interconnector variables are for the energy service
        so no 'service' can be specified.

        >>> interconnector_coefficients = pd.DataFrame({
        ...   'set': ['A', 'A', 'B'],
        ...   'interconnector': ['X', 'Y', 'X'],
        ...   'coefficient': [1.0, 1.0, -1.0]})

        >>> market.link_interconnectors_to_generic_constraints(interconnector_coefficients)

        Note all this does is save this information to the market object, linking to specific variable ids and
        constraint id occurs when the dispatch method is called.

        >>> print(market.generic_constraint_lhs['interconnectors'])
          set interconnector  coefficient
        0   A              X          1.0
        1   A              Y          1.0
        2   B              X         -1.0

        Parameters
        ----------
        unit_coefficients : pd.DataFrame

            =============  ==============================================================
            Columns:       Description:
            set            the unique identifier of the constraint set to map the
                           lhs coefficients to (as `str`)
            interconnetor  the interconnetor whose variables will be mapped to the lhs (as `str`)
            coefficient    the lhs coefficient (as `np.float64`)
            =============  ==============================================================

        Raises
        ------
        RepeatedRowError
            If there is more than one row for any set, interconnetor and service combination.
        ColumnDataTypeError
            If columns are not of the required type.
        MissingColumnError
            If the column 'set', 'interconnetor' or 'coefficient' is missing.
        UnexpectedColumn
            There is a column that is not 'set', 'interconnetor' or 'coefficient'.
        ColumnValues
            If there are inf or null values in the rhs coefficient.
        """
        self.generic_constraint_lhs['interconnectors'] = interconnector_coefficients

    def make_constraints_elastic(self, constraints_key, violation_cost='market_ceiling_price'):
        """Make a set of constraints elastic, so they can be violated at a predefined cost.

        If the string 'market_ceiling_price' is provided then the market_ceiling_price is used to set the
        violation cost. If an int or float is provided then this directly set the cost. If a pd.DataFrame
        is provided then it must contain the columns 'set' and 'cost', 'set' is used to match the cost to
        the constraints, sets in the constraints that do not appear in the pd.DataFrame will not be made
        elastic.

        Examples
        --------
        >>> import pandas as pd
        >>> from nempy import markets

        Create a market instance.

        >>> market = markets.Spot()

        Define a set of generic constraints and add them to the market.

        >>> generic_constraint_parameters = pd.DataFrame({
        ...   'set': ['A', 'B'],
        ...   'type': ['>=', '<='],
        ...   'rhs': [10.0, -100.0]})

        >>> market.set_generic_constraints(generic_constraint_parameters)

        Now the market should have a set of generic constraints.

        >>> print(market.constraints_rhs_and_type['generic'])
          set  constraint_id type    rhs
        0   A              0   >=   10.0
        1   B              1   <= -100.0

        Now these constraints can be made elastic. Leaving the key word argument at its default value means
        the market_ceiling_price will be used to set the violation cost.

        >>> market.make_constraints_elastic('generic')

        Now the market will contain extra decision variables to capture the cost of violating the constraint.

        >>> print(market.decision_variables['generic_deficit'])
           variable_id  lower_bound  upper_bound        type
        0            0          0.0          inf  continuous
        1            1          0.0          inf  continuous

        >>> print(market.objective_function_components['generic_deficit'])
           variable_id     cost
        0            0  14000.0
        1            1  14000.0

        These will be mapped to the constraints

        >>> print(market.lhs_coefficients['generic_deficit'])
           variable_id  constraint_id  coefficient
        0            0              0          1.0
        1            1              1         -1.0

        If we provided a specific violation cost then this is used instead of the market_ceiling_price.

        >>> market.make_constraints_elastic('generic', violation_cost=1000.0)

        >>> print(market.objective_function_components['generic_deficit'])
           variable_id    cost
        0            2  1000.0
        1            3  1000.0

        If a pd.DataFrame is provided then we can set cost on a constraint basis.

        >>> violation_cost = pd.DataFrame({
        ...   'set': ['A', 'B'],
        ...   'cost': [1000.0, 2000.0]})

        >>> market.make_constraints_elastic('generic', violation_cost=violation_cost)

        >>> print(market.objective_function_components['generic_deficit'])
           variable_id    cost
        0            4  1000.0
        1            5  2000.0

        Note will the variable id get incremented with every use of the method only the latest set of variables are
        used.

        Parameters
        ----------
        constraints_key : str
            The key used to reference the constraint set in the dict self.market_constraints_rhs_and_type or
            self.constraints_rhs_and_type. See the documentation for creating the constraint set to get this key.

        violation_cost : str or float or int or pd.DataFrame

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If violation_cost is not str, numeric or pd.DataFrame.
        ModelBuildError
            If the constraint_key provided does not match any existing constraints.
        MissingColumnError
            If violation_cost is a pd.DataFrame and does not contain the columns set and cost.
            Or if the constraints to be made elastic do not have the set idenetifier.
        RepeatedRowError
            If violation_cost is a pd.DataFrame and has more than one row per set.
        ColumnDataTypeError
            If violation_cost is a pd.DataFrame and the column set is not str and the column
            cost is not numeric.
        """

        if constraints_key in self.market_constraints_rhs_and_type.keys():
            rhs_and_type = self.market_constraints_rhs_and_type[constraints_key].copy()
        elif constraints_key in self.constraints_rhs_and_type.keys():
            rhs_and_type = self.constraints_rhs_and_type[constraints_key].copy()
        else:
            check.ModelBuildError('constraints_key does not exist.')

        # Add the column cost to the constraints definitions.
        if isinstance(violation_cost, str) and violation_cost == 'market_ceiling_price':
            rhs_and_type['cost'] = self.market_ceiling_price
        elif isinstance(violation_cost, (int, float)) and not isinstance(violation_cost, bool):
            rhs_and_type['cost'] = violation_cost
        elif isinstance(violation_cost, pd.DataFrame):
            # Check pd.DataFrame columns needed exist and are of the right type.
            if 'set' in violation_cost.columns and 'cost' in violation_cost.columns:
                if not all(violation_cost.apply(lambda x: type(x['set']) == str, axis=1)):
                    raise check.ColumnDataTypeError("Column 'set' in violation should have type str")
                if np.float64 != violation_cost['cost'].dtype:
                    raise check.ColumnDataTypeError("Column 'cost' in violation_cost should have type np.float64")
            else:
                check.MissingColumnError("Column 'set' or 'cost' missing from violation_cost")
            # Check only one row per set.
            if len(violation_cost.index) != len(violation_cost.drop_duplicates('set')):
                raise check.RepeatedRowError("violation_cost should only have one row for each set")
            # Check the constraints being made elastic have column set.
            if 'set' not in violation_cost.columns:
                check.MissingColumnError("Column 'set' not in constraints to make elastic")
            rhs_and_type = pd.merge(rhs_and_type, violation_cost.loc[:, ['set', 'cost']], on='set')
        else:
            ValueError("Input for violation cost can only be 'market_ceiling_price', numeric or a pd.Dataframe")

        deficit_variables, lhs = elastic_constraints.create_deficit_variables(rhs_and_type, self.next_variable_id)
        self.decision_variables[constraints_key + '_deficit'] = \
            deficit_variables.loc[:, ['variable_id', 'lower_bound', 'upper_bound', 'type']]
        self.objective_function_components[constraints_key + '_deficit'] = \
            deficit_variables.loc[:, ['variable_id', 'cost']]
        self.lhs_coefficients[constraints_key + '_deficit'] = lhs
        self.next_variable_id = max(deficit_variables['variable_id']) + 1

    #@check.pre_dispatch
    def dispatch(self, price_market_constraints=True):
        """Combines the elements of the linear program and solves to find optimal dispatch.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of prices for the bids.

        >>> price_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [50.0, 100.0],
        ...     '2': [100.0, 130.0],
        ...     '3': [100.0, 150.0]})

        Create the objective function components corresponding to the the energy bids.

        >>> simple_market.set_unit_price_bids(price_bids)

        Define a demand level in each region.

        >>> demand = pd.DataFrame({
        ...     'region': ['NSW'],
        ...     'demand': [100.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_demand_constraints(demand)

        Call the dispatch method.

        >>> simple_market.dispatch()

        Now the market dispatch can be retrieved.

        >>> print(simple_market.get_unit_dispatch())
          unit service  dispatch
        0    A  energy      45.0
        1    B  energy      55.0

        And the market prices can be retrieved.

        >>> print(simple_market.get_energy_prices())
          region  price
        0    NSW  130.0

        Returns
        -------
        None

        Raises
        ------
            ModelBuildError
                If a model build process is incomplete, i.e. there are energy bids but not energy demand set.
        """

        # Create a data frame containing all fully defined components of the constraint matrix lhs. If there are none
        # then just create a place holder empty pd.DataFrame.
        if len(self.lhs_coefficients.values()) > 0:
            constraints_lhs = pd.concat(list(self.lhs_coefficients.values()))
        else:
            constraints_lhs = pd.DataFrame()

        # Get a pd.DataFrame mapping the generic constraint sets to their constraint ids.
        generic_constraint_ids = solver_interface.create_mapping_of_generic_constraint_sets_to_constraint_ids(
            self.constraints_rhs_and_type, self.market_constraints_rhs_and_type)

        # If there are any generic constraints create their lhs definitions.
        if generic_constraint_ids is not None:
            generic_lhs = []
            # If units have been added to the generic lhs then find the relevant variable ids and map them to the
            # constraint.
            if 'unit' in self.generic_constraint_lhs and 'bids' in self.variable_to_constraint_map['unit_level']:
                generic_constraint_units = self.generic_constraint_lhs['unit']
                unit_bids_to_constraint_map = self.variable_to_constraint_map['unit_level']['bids']
                unit_lhs = solver_interface.create_unit_level_generic_constraint_lhs(generic_constraint_units,
                                                                                     generic_constraint_ids,
                                                                                     unit_bids_to_constraint_map)
                generic_lhs.append(unit_lhs)
            # If regions have been added to the generic lhs then find the relevant variable ids and map them to the
            # constraint.
            if 'region' in self.generic_constraint_lhs and 'bids' in self.variable_to_constraint_map['regional']:
                generic_constraint_region = self.generic_constraint_lhs['region']
                unit_bids_to_constraint_map = self.variable_to_constraint_map['regional']['bids']
                regional_lhs = solver_interface.create_region_level_generic_constraint_lhs(generic_constraint_region,
                                                                                           generic_constraint_ids,
                                                                                           unit_bids_to_constraint_map)
                generic_lhs.append(regional_lhs)
            # If interconnectors have been added to the generic lhs then find the relevant variable ids and map them
            # to the constraint.
            if 'interconnectors' in self.generic_constraint_lhs and 'interconnectors' in self.decision_variables:
                generic_constraint_interconnectors = self.generic_constraint_lhs['interconnectors']
                interconnector_bids_to_constraint_map = self.decision_variables['interconnectors']
                interconnector_lhs = solver_interface.create_interconnector_generic_constraint_lhs(
                    generic_constraint_interconnectors, generic_constraint_ids, interconnector_bids_to_constraint_map)
                generic_lhs.append(interconnector_lhs)
            # Add the generic lhs definitions the cumulative lhs pd.DataFrame.
            constraints_lhs = pd.concat([constraints_lhs] + generic_lhs)

        # If there are constraints that have been defined on a regional basis then create the constraints lhs
        # definition by mapping to all the variables that have been defined for the corresponding region and service.
        if len(self.constraint_to_variable_map['regional']) > 0:
            constraints = pd.concat(list(self.constraint_to_variable_map['regional'].values()))
            decision_variables = pd.concat(list(self.variable_to_constraint_map['regional'].values()))
            regional_constraints_lhs = solver_interface.create_lhs(constraints, decision_variables,
                                                                   ['region', 'service'])
            # Add the lhs definitions the cumulative lhs pd.DataFrame.
            constraints_lhs = pd.concat([constraints_lhs, regional_constraints_lhs])

        # If there are constraints that have been defined on a unit basis then create the constraints lhs
        # definition by mapping to all the variables that have been defined for the corresponding unit and service.
        if len(self.constraint_to_variable_map['unit_level']) > 0:
            constraints = pd.concat(list(self.constraint_to_variable_map['unit_level'].values()))
            decision_variables = pd.concat(list(self.variable_to_constraint_map['unit_level'].values()))
            unit_constraints_lhs = solver_interface.create_lhs(constraints, decision_variables, ['unit', 'service'])
            # Add the lhs definitions the cumulative lhs pd.DataFrame.
            constraints_lhs = pd.concat([constraints_lhs, unit_constraints_lhs])

        # Create the interface to the solver.
        si = solver_interface.InterfaceToSolver()

        if self.decision_variables:
            # Combine dictionary of pd.DataFrames into a single pd.DataFrame for processing by the interface.
            variable_definitions = pd.concat(self.decision_variables)
            si.add_variables(variable_definitions)
        else:
            raise check.ModelBuildError('The market could not be dispatch because no variables have been created')

        # If interconnectors with losses are being used, create special ordered sets for modelling losses.
        if 'interpolation_weights' in self.decision_variables.keys():
            special_ordered_sets = self.decision_variables['interpolation_weights']
            special_ordered_sets = \
                special_ordered_sets.rename(columns={'interconnector': 'sos_id', 'loss_segment': 'position'})
            si.add_sos_type_2(special_ordered_sets)

        # If Costs have been defined for bids or constraints then add an objective function.
        if self.objective_function_components:
            # Combine components of objective function into a single pd.DataFrame
            objective_function_definition = pd.concat(self.objective_function_components)
            si.add_objective_function(objective_function_definition)

        # Collect all constraint rhs and type definitions into a single pd.DataFrame.
        constraints_rhs_and_type = []
        if self.constraints_rhs_and_type:
            constraints_rhs_and_type.append(pd.concat(self.constraints_rhs_and_type))
        if self.market_constraints_rhs_and_type:
            constraints_rhs_and_type.append(pd.concat(self.market_constraints_rhs_and_type))
        if self.constraints_dynamic_rhs_and_type:
            constraints_dynamic_rhs_and_type = pd.concat(self.constraints_dynamic_rhs_and_type)
            # Create the rhs for the dynamic constraints.
            constraints_dynamic_rhs_and_type['rhs'] = constraints_dynamic_rhs_and_type. \
                apply(lambda x: si.variables[x['rhs_variable_id']], axis=1)
            constraints_rhs_and_type.append(constraints_dynamic_rhs_and_type)
        if len(constraints_rhs_and_type) > 0:
            constraints_rhs_and_type = pd.concat(constraints_rhs_and_type)
            si.add_constraints(constraints_lhs, constraints_rhs_and_type)

        si.optimize()

        # Find the slack in constraints.
        if self.constraints_rhs_and_type:
            for constraint_group in self.constraints_rhs_and_type:
                self.constraints_rhs_and_type[constraint_group]['slack'] = \
                    si.get_slack_in_constraints(self.constraints_rhs_and_type[constraint_group])
        if self.market_constraints_rhs_and_type:
            for constraint_group in self.market_constraints_rhs_and_type:
                self.market_constraints_rhs_and_type[constraint_group]['slack'] = \
                    si.get_slack_in_constraints(self.market_constraints_rhs_and_type[constraint_group])
        if self.constraints_dynamic_rhs_and_type:
            for constraint_group in self.constraints_dynamic_rhs_and_type:
                self.constraints_dynamic_rhs_and_type[constraint_group]['slack'] = \
                    si.get_slack_in_constraints(self.constraints_dynamic_rhs_and_type[constraint_group])

        # Get decision variable optimal values
        for var_group in self.decision_variables:
            self.decision_variables[var_group]['value'] = \
                si.get_optimal_values_of_decision_variables(self.decision_variables[var_group])

        # If there are market constraints then calculate their associated prices.
        if self.market_constraints_rhs_and_type and price_market_constraints:
            for constraint_group in self.market_constraints_rhs_and_type:
                constraints_to_price = list(self.market_constraints_rhs_and_type[constraint_group]['constraint_id'])
                prices = si.price_constraints(constraints_to_price)
                self.market_constraints_rhs_and_type[constraint_group]['price'] = \
                    self.market_constraints_rhs_and_type[constraint_group]['constraint_id'].map(prices)

    def get_unit_dispatch(self):
        """Retrieves the energy dispatch for each unit.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of prices for the bids.

        >>> price_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [50.0, 100.0],
        ...     '2': [100.0, 130.0],
        ...     '3': [100.0, 150.0]})

        Create the objective function components corresponding to the the energy bids.

        >>> simple_market.set_unit_price_bids(price_bids)

        Define a demand level in each region.

        >>> demand = pd.DataFrame({
        ...     'region': ['NSW'],
        ...     'demand': [100.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_demand_constraints(demand)

        Call the dispatch method.

        >>> simple_market.dispatch()

        Now the market dispatch can be retrieved.

        >>> print(simple_market.get_unit_dispatch())
          unit service  dispatch
        0    A  energy      45.0
        1    B  energy      55.0

        Returns
        -------
        pd.DataFrame

        Raises
        ------
            ModelBuildError
                If a model build process is incomplete, i.e. there are energy bids but not energy demand set.
        """
        dispatch = self.decision_variables['bids'].loc[:, ['unit', 'service', 'value']]
        dispatch.columns = ['unit', 'service', 'dispatch']
        return dispatch.groupby(['unit', 'service'], as_index=False).sum()

    def get_energy_prices(self):
        """Retrieves the energy price in each market region.

        Energy prices are the shadow prices of the demand constraint in each market region.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     'region': ['NSW', 'NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have two units called A and B, with three bid bands.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [20.0, 50.0],
        ...     '2': [20.0, 30.0],
        ...     '3': [5.0, 10.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of prices for the bids.

        >>> price_bids = pd.DataFrame({
        ...     'unit': ['A', 'B'],
        ...     '1': [50.0, 100.0],
        ...     '2': [100.0, 130.0],
        ...     '3': [100.0, 150.0]})

        Create the objective function components corresponding to the the energy bids.

        >>> simple_market.set_unit_price_bids(price_bids)

        Define a demand level in each region.

        >>> demand = pd.DataFrame({
        ...     'region': ['NSW'],
        ...     'demand': [100.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_demand_constraints(demand)

        Call the dispatch method.

        >>> simple_market.dispatch()

        Now the market prices can be retrieved.

        >>> print(simple_market.get_energy_prices())
          region  price
        0    NSW  130.0

        Returns
        -------
        pd.DateFrame

        Raises
        ------
            ModelBuildError
                If a model build process is incomplete, i.e. there are energy bids but not energy demand set.
        """
        prices = self.market_constraints_rhs_and_type['demand'].loc[:, ['region', 'price']]
        return prices

    def get_fcas_prices(self):
        """Retrives the price associated with each set of FCAS requirement constraints.

        Returns
        -------
        pd.DateFrame
        """
        prices = pd.merge(
            self.constraint_to_variable_map['regional']['fcas'].loc[:, ['service', 'region', 'constraint_id']],
            self.market_constraints_rhs_and_type['fcas'].loc[:, ['set', 'price', 'constraint_id']], on='constraint_id')
        prices = prices.groupby(['region', 'service'], as_index=False).aggregate({'price': 'max'})
        return prices

    def get_interconnector_flows(self):
        """Retrieves the  flows for each interconnector.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A'],
        ...     'region': ['NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have just one unit that can provide 100 MW in NSW.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A'],
        ...     '1': [100.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of prices for the bids.

        >>> price_bids = pd.DataFrame({
        ...     'unit': ['A'],
        ...     '1': [80.0]})

        Create the objective function components corresponding to the the energy bids.

        >>> simple_market.set_unit_price_bids(price_bids)

        Define a demand level in each region, no power is required in NSW and 90.0 MW is required in VIC.

        >>> demand = pd.DataFrame({
        ...     'region': ['NSW', 'VIC'],
        ...     'demand': [0.0, 90.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_demand_constraints(demand)

        Define a an interconnector between NSW and VIC so generator can A can be used to meet demand in VIC.

        >>> interconnector = pd.DataFrame({
        ...     'interconnector': ['inter_one'],
        ...     'to_region': ['VIC'],
        ...     'from_region': ['NSW'],
        ...     'max': [100.0],
        ...     'min': [-100.0]})

        Create the interconnector.

        >>> simple_market.set_interconnectors(interconnector)

        Call the dispatch method.

        >>> simple_market.dispatch()

        Now the market dispatch can be retrieved.

        >>> print(simple_market.get_unit_dispatch())
          unit service  dispatch
        0    A  energy      90.0

        And the interconnector flows can be retrieved.

        >>> print(simple_market.get_interconnector_flows())
          interconnector  flow
        0      inter_one  90.0

        Returns
        -------
        pd.DataFrame

        Raises
        ------
            ModelBuildError
                If a model build process is incomplete, i.e. there are energy bids but not energy demand set.
        """
        flow = self.decision_variables['interconnectors'].loc[:, ['interconnector', 'value']]
        flow.columns = ['interconnector', 'flow']
        if 'interconnector_losses' in self.decision_variables:
            losses = self.decision_variables['interconnector_losses'].loc[:, ['interconnector', 'value']]
            losses.columns = ['interconnector', 'losses']
            flow = pd.merge(flow, losses, 'left', on='interconnector')

        return flow.reset_index(drop=True)

    def get_region_dispatch_summary(self):
        """Calculates a dispatch summary at the regional level.

        Examples
        --------
        This is an example of the minimal set of steps for using this method.

        Import required packages.

        >>> import pandas as pd
        >>> from nempy import markets

        Initialise the market instance.

        >>> simple_market = markets.Spot()

        Define the unit information data set needed to initialise the market, in this example all units are in the same
        region.

        >>> unit_info = pd.DataFrame({
        ...     'unit': ['A'],
        ...     'region': ['NSW']})

        Add unit information

        >>> simple_market.set_unit_info(unit_info)

        Define a set of bids, in this example we have just one unit that can provide 100 MW in NSW.

        >>> volume_bids = pd.DataFrame({
        ...     'unit': ['A'],
        ...     '1': [100.0]})

        Create energy unit bid decision variables.

        >>> simple_market.set_unit_volume_bids(volume_bids)

        Define a set of prices for the bids.

        >>> price_bids = pd.DataFrame({
        ...     'unit': ['A'],
        ...     '1': [80.0]})

        Create the objective function components corresponding to the the energy bids.

        >>> simple_market.set_unit_price_bids(price_bids)

        Define a demand level in each region, no power is required in NSW and 90.0 MW is required in VIC.

        >>> demand = pd.DataFrame({
        ...     'region': ['NSW', 'VIC'],
        ...     'demand': [0.0, 90.0]})

        Create unit capacity based constraints.

        >>> simple_market.set_demand_constraints(demand)

        Define a an interconnector between NSW and VIC so generator can A can be used to meet demand in VIC.

        >>> interconnector = pd.DataFrame({
        ...     'interconnector': ['inter_one'],
        ...     'to_region': ['VIC'],
        ...     'from_region': ['NSW'],
        ...     'max': [100.0],
        ...     'min': [-100.0]})

        Create the interconnector.

        >>> simple_market.set_interconnectors(interconnector)

        Define the interconnector loss function. In this case losses are always 5 % of line flow.

        >>> def constant_losses(flow=None):
        ...     return abs(flow) * 0.05

        Define the function on a per interconnector basis. Also details how the losses should be proportioned to the
        connected regions.

        >>> loss_functions = pd.DataFrame({
        ...    'interconnector': ['inter_one'],
        ...    'from_region_loss_share': [0.5],  # losses are shared equally.
        ...    'loss_function': [constant_losses]})

        Define The points to linearly interpolate the loss function between. In this example the loss function is
        linear so only three points are needed, but if a non linear loss function was used then more points would
        result in a better approximation.

        >>> interpolation_break_points = pd.DataFrame({
        ...    'interconnector': ['inter_one', 'inter_one', 'inter_one'],
        ...    'loss_segment': [1, 2, 3],
        ...    'break_point': [-120.0, 0.0, 100]})

        >>> simple_market.set_interconnector_losses(loss_functions, interpolation_break_points)

        Call the dispatch method.

        >>> simple_market.dispatch()

        Now the region dispatch summary can be retreived.

        >>> print(simple_market.get_region_dispatch_summary())
          region   dispatch     inflow  interconnector_losses
        0    NSW  94.615385 -92.307692               2.307692

        Returns
        -------
        pd.DataFrame

            =====================    =================================================================
            Columns:                 Description:
            region                   unique identifier of a market region, required (as `str`)
            dispatch                 the net dispatch of units inside a region i.e. generators dispatch
                                     - load dispatch, in MW. (as `np.float64`)
            inflow                   the net inflow from interconnectors, not including losses, in MW
                                     (as `np.float64`)
            interconnector_losses    interconnector losses attributed to region, in MW, (as `np.float64`)
            =====================    =================================================================
        """
        dispatch_summary = self._get_net_unit_dispatch_by_region()
        if self._interconnectors_in_market():
            interconnector_inflow = self._get_interconnector_inflow_by_region()
            dispatch_summary = pd.merge(dispatch_summary, interconnector_inflow, on='region')
            transmission_losses = self._get_transmission_losses()
            dispatch_summary = pd.merge(dispatch_summary, transmission_losses, on='region')
        if self._interconnectors_have_losses():
            interconnector_losses = self._get_interconnector_losses_by_region()
            dispatch_summary = pd.merge(dispatch_summary, interconnector_losses, on='region')
        return dispatch_summary

    def _get_net_unit_dispatch_by_region(self):

        unit_dispatch = self.get_unit_dispatch()
        unit_dispatch = unit_dispatch[unit_dispatch['service'] == 'energy']
        unit_dispatch_types = self.unit_info.loc[:, ['unit', 'region', 'dispatch_type']]
        unit_dispatch = pd.merge(unit_dispatch, unit_dispatch_types, on='unit')

        def make_load_dispatch_negative(dispatch_type, dispatch):
            if dispatch_type == 'load':
                dispatch = -1 * dispatch
            return dispatch

        unit_dispatch['dispatch'] = \
            unit_dispatch.apply(lambda x: make_load_dispatch_negative(x['dispatch_type'], x['dispatch']), axis=1)

        unit_dispatch = unit_dispatch.groupby('region', as_index=False).aggregate({'dispatch': 'sum'})
        return unit_dispatch

    def _interconnectors_in_market(self):
        return self.interconnector_directions is not None

    def _get_interconnector_inflow_by_region(self):

        def calc_inflow_by_interconnector(interconnector_direction_coefficients, interconnector_flows):
            inflow = pd.merge(interconnector_direction_coefficients, interconnector_flows, on='interconnector')
            inflow['inflow'] = inflow['flow'] * inflow['direction_coefficient']
            return inflow

        def calc_inflow_by_region(inflow):
            inflow = inflow.groupby('region', as_index=False).aggregate({'inflow': 'sum'})
            return inflow

        interconnector_flows = self.get_interconnector_flows()
        interconnector_direction_coefficients = self._get_interconnector_inflow_coefficients()
        inflow = calc_inflow_by_interconnector(interconnector_direction_coefficients, interconnector_flows)
        inflow = calc_inflow_by_region(inflow)

        return inflow

    def _get_interconnector_inflow_coefficients(self):

        def define_positive_inflows():
            inflow_direction = self.interconnector_directions.loc[:, ['interconnector', 'to_region']]
            inflow_direction['direction_coefficient'] = 1.0
            inflow_direction.columns = ['interconnector', 'region', 'direction_coefficient']
            return inflow_direction

        def define_negative_inflows():
            outflow_direction = self.interconnector_directions.loc[:, ['interconnector', 'from_region']]
            outflow_direction['direction_coefficient'] = -1.0
            outflow_direction.columns = ['interconnector', 'region', 'direction_coefficient']
            return outflow_direction

        positive_inflow = define_positive_inflows()
        negative_inflow = define_negative_inflows()
        inflow_coefficients = pd.concat([positive_inflow, negative_inflow])

        return inflow_coefficients

    def _interconnectors_have_losses(self):
        return self.interconnector_loss_shares is not None

    def _get_interconnector_losses_by_region(self):
        from_region_loss_shares = self._get_from_region_loss_shares()
        to_region_loss_shares = self._get_to_region_loss_shares()
        loss_shares = pd.concat([from_region_loss_shares, to_region_loss_shares])
        losses = self.get_interconnector_flows().loc[:, ['interconnector', 'losses']]
        losses = pd.merge(losses, loss_shares, on='interconnector')
        losses['interconnector_losses'] = losses['losses'] * losses['loss_share']
        self._get_transmission_losses()
        losses = losses.groupby('region', as_index=False).aggregate({'interconnector_losses': 'sum'})
        return losses

    def _get_from_region_loss_shares(self):
        from_region_loss_share = self._get_loss_shares('from_region')
        from_region_loss_share = from_region_loss_share.rename(columns={'from_region_loss_share': 'loss_share'})
        return from_region_loss_share

    def _get_to_region_loss_shares(self):
        to_region_loss_share = self._get_loss_shares('to_region')
        to_region_loss_share['loss_share'] = 1 - to_region_loss_share['from_region_loss_share']
        to_region_loss_share = to_region_loss_share.drop('from_region_loss_share', axis=1)
        return to_region_loss_share

    def _get_loss_shares(self, region_type):
        from_region_loss_share = self.interconnector_loss_shares
        regions = self.interconnector_directions.loc[:, ['interconnector', region_type]]
        regions = regions.rename(columns={region_type: 'region'})
        from_region_loss_share = pd.merge(from_region_loss_share, regions, on='interconnector')
        from_region_loss_share = from_region_loss_share.loc[:, ['interconnector', 'region', 'from_region_loss_share']]
        return from_region_loss_share

    def _get_transmission_losses(self):
        interconnector_directions = self.interconnector_directions
        loss_factors = hf.stack_columns(interconnector_directions, ['interconnector'],
                                        ['from_region_loss_factor', 'to_region_loss_factor'], 'direction',
                                        'loss_factor')
        interconnector_directions = hf.stack_columns(interconnector_directions, ['interconnector'],
                                                     ['to_region', 'from_region'], 'direction', 'region')
        loss_factors['direction'] = loss_factors['direction'].apply(lambda x: x.replace('_loss_factor', ''))
        loss_factors = pd.merge(loss_factors, interconnector_directions, on=['interconnector', 'direction'])
        flows_and_losses = self.get_interconnector_flows()
        flows_and_losses = pd.merge(flows_and_losses, loss_factors, on='interconnector')

        def calc_losses(direction, flow, loss_factor):
            if (direction == 'to_region' and flow >= 0.0) or (direction == 'from_region' and flow <= 0.0):
                losses = flow * (1 - loss_factor)
            elif (direction == 'to_region' and flow < 0.0) or (direction == 'from_region' and flow > 0.0):
                losses = abs(flow) - (abs(flow) / loss_factor)
            return losses

        flows_and_losses['transmission_losses'] = \
            flows_and_losses.apply(lambda x: calc_losses(x['direction'], x['flow'], x['loss_factor']), axis=1)
        flows_and_losses = flows_and_losses.groupby('region', as_index=False).aggregate({'transmission_losses': 'sum'})
        return flows_and_losses

    def get_fcas_availability(self):
        """Get the availability of fcas service on a unit level, after constraints.

        Examples
        --------
        This example dispatches a simple fcas market and the shows the resulting fcas availability.

        >>> from nempy import markets

        Volume of each bid.

        >>> volume_bids = pd.DataFrame({
        ...   'unit': ['A', 'A', 'B', 'B', 'B'],
        ...   'service': ['energy', 'raise_6s', 'energy', 'raise_6s', 'raise_reg'],
        ...   '1': [100.0, 10.0, 110.0, 15.0, 15.0]})

        Price of each bid.

        >>> price_bids = pd.DataFrame({
        ...   'unit': ['A', 'A', 'B', 'B', 'B'],
        ...   'service': ['energy', 'raise_6s', 'energy', 'raise_6s', 'raise_reg'],
        ...   '1': [50.0, 35.0, 60.0, 20.0, 30.0]})

        Participant defined operational constraints on FCAS enablement.

        >>> fcas_trapeziums = pd.DataFrame({
        ...   'unit': ['B', 'B', 'A'],
        ...   'service': ['raise_reg', 'raise_6s', 'raise_6s'],
        ...   'max_availability': [15.0, 15.0, 10.0],
        ...   'enablement_min': [50.0, 50.0, 70.0],
        ...   'low_break_point': [65.0, 65.0, 80.0],
        ...   'high_break_point': [95.0, 95.0, 100.0],
        ...   'enablement_max': [110.0, 110.0, 110.0]})

        Unit locations.

        >>> unit_info = pd.DataFrame({
        ...   'unit': ['A', 'B'],
        ...   'region': ['NSW', 'NSW']})

        The demand in the region\s being dispatched.

        >>> demand = pd.DataFrame({
        ...   'region': ['NSW'],
        ...   'demand': [195.0]})

        FCAS requirement in the region\s being dispatched.

        >>> fcas_requirements = pd.DataFrame({
        ...   'set': ['nsw_regulation_requirement', 'nsw_raise_6s_requirement'],
        ...   'region': ['NSW', 'NSW'],
        ...   'service': ['raise_reg', 'raise_6s'],
        ...   'volume': [10.0, 10.0]})

        Create the market model with unit service bids.

        >>> simple_market = markets.Spot()
        >>> simple_market.set_unit_info(unit_info)
        >>> simple_market.set_unit_volume_bids(volume_bids)
        >>> simple_market.set_unit_price_bids(price_bids)

        Create constraints that enforce the top of the FCAS trapezium.

        >>> fcas_availability = fcas_trapeziums.loc[:, ['unit', 'service', 'max_availability']]
        >>> simple_market.set_fcas_max_availability(fcas_availability)

        Create constraints the enforce the lower and upper slope of the FCAS regulation service trapeziums.

        >>> regulation_trapeziums = fcas_trapeziums[fcas_trapeziums['service'] == 'raise_reg']
        >>> simple_market.set_energy_and_regulation_capacity_constraints(regulation_trapeziums)

        Create constraints that enforce the lower and upper slope of the FCAS contingency
        trapezium. These constrains also scale slopes of the trapezium to ensure the
        co-dispatch of contingency and regulation services is technically feasible.

        >>> contingency_trapeziums = fcas_trapeziums[fcas_trapeziums['service'] == 'raise_6s']
        >>> simple_market.set_joint_capacity_constraints(contingency_trapeziums)

        Set the demand for energy.

        >>> simple_market.set_demand_constraints(demand)

        Set the required volume of FCAS services.

        >>> simple_market.set_fcas_requirements_constraints(fcas_requirements)

        Calculate dispatch and pricing

        >>> simple_market.dispatch()

        Return the total dispatch of each unit in MW.

        >>> print(simple_market.get_unit_dispatch())
          unit    service  dispatch
        0    A     energy     100.0
        1    A   raise_6s       5.0
        2    B     energy      95.0
        3    B   raise_6s       5.0
        4    B  raise_reg      10.0

        Return the constrained availability of each units fcas service.

        >>> print(simple_market.get_fcas_availability())
          unit    service  availability
        0    A   raise_6s          10.0
        1    B   raise_6s           5.0
        2    B  raise_reg          10.0

        Returns
        -------

        """
        fcas_variable_slack = []
        for constraint_type in ['fcas_max_availability', 'joint_ramping', 'joint_capacity',
                                'energy_and_regulation_capacity']:
            if constraint_type in self.constraints_rhs_and_type.keys():
                service_coefficients = self.constraint_to_variable_map['unit_level'][constraint_type]
                service_coefficients = service_coefficients.loc[:, ['constraint_id', 'unit', 'service', 'coefficient']]
                constraint_slack = self.constraints_rhs_and_type[constraint_type].loc[:, ['constraint_id', 'slack']]
                slack_temp = pd.merge(service_coefficients, constraint_slack, on='constraint_id')
                fcas_variable_slack.append(slack_temp)

        fcas_variable_slack = pd.concat(fcas_variable_slack)
        fcas_variable_slack['service_slack'] = fcas_variable_slack['slack'] / fcas_variable_slack['coefficient'].abs()
        fcas_variable_slack = \
            fcas_variable_slack.groupby(['unit', 'service'], as_index=False).aggregate({'service_slack': 'min'})
        fcas_variable_slack = fcas_variable_slack[fcas_variable_slack['service'] != 'energy']

        dispatch_levels = self.get_unit_dispatch()

        fcas_availability = pd.merge(fcas_variable_slack, dispatch_levels, on=['unit', 'service'])

        fcas_availability['availability'] = fcas_availability['dispatch'] + fcas_availability['service_slack']
        return fcas_availability.loc[:, ['unit', 'service', 'availability']]
