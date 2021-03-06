import numpy as np
import pytest

from pandas import (
    DataFrame,
    Series,
    date_range,
)
import pandas._testing as tm
from pandas.api.indexers import (
    BaseIndexer,
    FixedForwardWindowIndexer,
)
from pandas.core.indexers.objects import (
    ExpandingIndexer,
    VariableOffsetWindowIndexer,
)

from pandas.tseries.offsets import BusinessDay


def test_bad_get_window_bounds_signature():
    class BadIndexer(BaseIndexer):
        def get_window_bounds(self):
            return None

    indexer = BadIndexer()
    with pytest.raises(ValueError, match="BadIndexer does not implement"):
        Series(range(5)).rolling(indexer)


def test_expanding_indexer():
    s = Series(range(10))
    indexer = ExpandingIndexer()
    result = s.rolling(indexer).mean()
    expected = s.expanding().mean()
    tm.assert_series_equal(result, expected)


def test_indexer_constructor_arg():
    # Example found in computation.rst
    use_expanding = [True, False, True, False, True]
    df = DataFrame({"values": range(5)})

    class CustomIndexer(BaseIndexer):
        def get_window_bounds(self, num_values, min_periods, center, closed):
            start = np.empty(num_values, dtype=np.int64)
            end = np.empty(num_values, dtype=np.int64)
            for i in range(num_values):
                if self.use_expanding[i]:
                    start[i] = 0
                    end[i] = i + 1
                else:
                    start[i] = i
                    end[i] = i + self.window_size
            return start, end

    indexer = CustomIndexer(window_size=1, use_expanding=use_expanding)
    result = df.rolling(indexer).sum()
    expected = DataFrame({"values": [0.0, 1.0, 3.0, 3.0, 10.0]})
    tm.assert_frame_equal(result, expected)


def test_indexer_accepts_rolling_args():
    df = DataFrame({"values": range(5)})

    class CustomIndexer(BaseIndexer):
        def get_window_bounds(self, num_values, min_periods, center, closed):
            start = np.empty(num_values, dtype=np.int64)
            end = np.empty(num_values, dtype=np.int64)
            for i in range(num_values):
                if center and min_periods == 1 and closed == "both" and i == 2:
                    start[i] = 0
                    end[i] = num_values
                else:
                    start[i] = i
                    end[i] = i + self.window_size
            return start, end

    indexer = CustomIndexer(window_size=1)
    result = df.rolling(indexer, center=True, min_periods=1, closed="both").sum()
    expected = DataFrame({"values": [0.0, 1.0, 10.0, 3.0, 4.0]})
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize("constructor", [Series, DataFrame])
@pytest.mark.parametrize(
    "func,np_func,expected,np_kwargs",
    [
        ("count", len, [3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 2.0, np.nan], {}),
        ("min", np.min, [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 6.0, 7.0, 8.0, np.nan], {}),
        (
            "max",
            np.max,
            [2.0, 3.0, 4.0, 100.0, 100.0, 100.0, 8.0, 9.0, 9.0, np.nan],
            {},
        ),
        (
            "std",
            np.std,
            [
                1.0,
                1.0,
                1.0,
                55.71654452,
                54.85739087,
                53.9845657,
                1.0,
                1.0,
                0.70710678,
                np.nan,
            ],
            {"ddof": 1},
        ),
        (
            "var",
            np.var,
            [
                1.0,
                1.0,
                1.0,
                3104.333333,
                3009.333333,
                2914.333333,
                1.0,
                1.0,
                0.500000,
                np.nan,
            ],
            {"ddof": 1},
        ),
        (
            "median",
            np.median,
            [1.0, 2.0, 3.0, 4.0, 6.0, 7.0, 7.0, 8.0, 8.5, np.nan],
            {},
        ),
    ],
)
@pytest.mark.filterwarnings("ignore:min_periods:FutureWarning")
def test_rolling_forward_window(constructor, func, np_func, expected, np_kwargs):
    # GH 32865
    values = np.arange(10.0)
    values[5] = 100.0

    indexer = FixedForwardWindowIndexer(window_size=3)

    match = "Forward-looking windows can't have center=True"
    with pytest.raises(ValueError, match=match):
        rolling = constructor(values).rolling(window=indexer, center=True)
        getattr(rolling, func)()

    match = "Forward-looking windows don't support setting the closed argument"
    with pytest.raises(ValueError, match=match):
        rolling = constructor(values).rolling(window=indexer, closed="right")
        getattr(rolling, func)()

    rolling = constructor(values).rolling(window=indexer, min_periods=2)
    result = getattr(rolling, func)()

    # Check that the function output matches the explicitly provided array
    expected = constructor(expected)
    tm.assert_equal(result, expected)

    # Check that the rolling function output matches applying an alternative
    # function to the rolling window object
    expected2 = constructor(rolling.apply(lambda x: np_func(x, **np_kwargs)))
    tm.assert_equal(result, expected2)

    # Check that the function output matches applying an alternative function
    # if min_periods isn't specified
    # GH 39604: After count-min_periods deprecation, apply(lambda x: len(x))
    # is equivalent to count after setting min_periods=0
    min_periods = 0 if func == "count" else None
    rolling3 = constructor(values).rolling(window=indexer, min_periods=min_periods)
    result3 = getattr(rolling3, func)()
    expected3 = constructor(rolling3.apply(lambda x: np_func(x, **np_kwargs)))
    tm.assert_equal(result3, expected3)


@pytest.mark.parametrize("constructor", [Series, DataFrame])
def test_rolling_forward_skewness(constructor):
    values = np.arange(10.0)
    values[5] = 100.0

    indexer = FixedForwardWindowIndexer(window_size=5)
    rolling = constructor(values).rolling(window=indexer, min_periods=3)
    result = rolling.skew()

    expected = constructor(
        [
            0.0,
            2.232396,
            2.229508,
            2.228340,
            2.229091,
            2.231989,
            0.0,
            0.0,
            np.nan,
            np.nan,
        ]
    )
    tm.assert_equal(result, expected)


@pytest.mark.parametrize(
    "func,expected",
    [
        ("cov", [2.0, 2.0, 2.0, 97.0, 2.0, -93.0, 2.0, 2.0, np.nan, np.nan]),
        (
            "corr",
            [
                1.0,
                1.0,
                1.0,
                0.8704775290207161,
                0.018229084250926637,
                -0.861357304646493,
                1.0,
                1.0,
                np.nan,
                np.nan,
            ],
        ),
    ],
)
def test_rolling_forward_cov_corr(func, expected):
    values1 = np.arange(10).reshape(-1, 1)
    values2 = values1 * 2
    values1[5, 0] = 100
    values = np.concatenate([values1, values2], axis=1)

    indexer = FixedForwardWindowIndexer(window_size=3)
    rolling = DataFrame(values).rolling(window=indexer, min_periods=3)
    # We are interested in checking only pairwise covariance / correlation
    result = getattr(rolling, func)().loc[(slice(None), 1), 0]
    result = result.reset_index(drop=True)
    expected = Series(expected)
    expected.name = result.name
    tm.assert_equal(result, expected)


@pytest.mark.parametrize(
    "closed,expected_data",
    [
        ["right", [0.0, 1.0, 2.0, 3.0, 7.0, 12.0, 6.0, 7.0, 8.0, 9.0]],
        ["left", [0.0, 0.0, 1.0, 2.0, 5.0, 9.0, 5.0, 6.0, 7.0, 8.0]],
    ],
)
def test_non_fixed_variable_window_indexer(closed, expected_data):
    index = date_range("2020", periods=10)
    df = DataFrame(range(10), index=index)
    offset = BusinessDay(1)
    indexer = VariableOffsetWindowIndexer(index=index, offset=offset)
    result = df.rolling(indexer, closed=closed).sum()
    expected = DataFrame(expected_data, index=index)
    tm.assert_frame_equal(result, expected)


def test_fixed_forward_indexer_count():
    # GH: 35579
    df = DataFrame({"b": [None, None, None, 7]})
    indexer = FixedForwardWindowIndexer(window_size=2)
    result = df.rolling(window=indexer, min_periods=0).count()
    expected = DataFrame({"b": [0.0, 0.0, 1.0, 1.0]})
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize(
    ("end_value", "values"), [(1, [0.0, 1, 1, 3, 2]), (-1, [0.0, 1, 0, 3, 1])]
)
@pytest.mark.parametrize(("func", "args"), [("median", []), ("quantile", [0.5])])
def test_indexer_quantile_sum(end_value, values, func, args):
    # GH 37153
    class CustomIndexer(BaseIndexer):
        def get_window_bounds(self, num_values, min_periods, center, closed):
            start = np.empty(num_values, dtype=np.int64)
            end = np.empty(num_values, dtype=np.int64)
            for i in range(num_values):
                if self.use_expanding[i]:
                    start[i] = 0
                    end[i] = max(i + end_value, 1)
                else:
                    start[i] = i
                    end[i] = i + self.window_size
            return start, end

    use_expanding = [True, False, True, False, True]
    df = DataFrame({"values": range(5)})

    indexer = CustomIndexer(window_size=1, use_expanding=use_expanding)
    result = getattr(df.rolling(indexer), func)(*args)
    expected = DataFrame({"values": values})
    tm.assert_frame_equal(result, expected)
