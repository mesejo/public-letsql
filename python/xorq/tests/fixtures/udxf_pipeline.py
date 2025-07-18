import operator

import toolz

import xorq as xo
from xorq import make_pandas_udf


field_name = "price_per_carat"
schema = xo.schema({"sum_price": "float64", "sum_carat": "float64"})
return_type = xo.dtype("float64")


@make_pandas_udf(
    schema=schema,
    return_type=return_type,
    name="my_udf",
)
def my_udf(df):
    return df["sum_carat"].div(df["sum_price"])


def do_agg(expr):
    return (
        expr.group_by("cut")
        .agg(
            xo._.price.sum().name("sum_price"),
            xo._.carat.sum().name("sum_carat"),
            xo._.color.nunique().name("nunique_color"),
        )
        .cast({"sum_price": "float64"})
    )


my_udf_on_expr = toolz.compose(
    operator.methodcaller("name", field_name), my_udf.on_expr
)

con = xo.connect()

diamonds = xo.examples.diamonds.fetch(backend=con)

input_expr = diamonds.pipe(do_agg)
process_df = operator.methodcaller("assign", **{field_name: my_udf.fn})
maybe_schema_in = input_expr.schema()
maybe_schema_out = xo.schema(input_expr.schema() | {field_name: return_type})
command = "diamonds_exchange_command"

expr = xo.expr.relations.flight_udxf(
    input_expr,
    process_df=process_df,
    maybe_schema_in=maybe_schema_in,
    maybe_schema_out=maybe_schema_out,
    con=con,
    make_udxf_kwargs={"name": my_udf.__name__, "command": command},
).order_by("cut")
