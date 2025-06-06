import pandas as pd
import toolz

import xorq as xo
from xorq.flight import FlightServer
from xorq.flight.exchanger import make_udxf


def dummy(df: pd.DataFrame):
    return pd.DataFrame({"row_count": [42]})


schema_in = xo.schema({"dummy": "int64"})
schema_out = xo.schema({"row_count": "int64"})
dummy_udxf = make_udxf(dummy, schema_in, schema_out)
flight_server = FlightServer(exchangers=[dummy_udxf])


if __name__ == "__pytest_main__":
    flight_server.serve()
    client = flight_server.client
    do_exchange = toolz.curry(client.do_exchange, dummy_udxf.command)
    do_exchange(xo.memtable({"dummy": [0]}, schema=schema_in))
    pytest_examples_passed = True
