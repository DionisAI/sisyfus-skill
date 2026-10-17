"""Frozen public API tracer; HTTP semantics have an independent later freeze.

Missing-module RED is availability only, not unvisited HTTP/Core/device proof.
Constructor/interface follows the exact Main frozen temporary-share contract.
"""
from __future__ import annotations
import importlib
import inspect
import pytest

MODULE='sisyfus.workers.share_gateway'


def test_frozen_share_gateway_public_api_availability():
    try:
        module=importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name!=MODULE:raise
        pytest.fail('missing temporary-share public module: '+MODULE,pytrace=False)
    cls=getattr(module,'ShareGateway',None)
    assert isinstance(cls,type),'missing ShareGateway public class'
    params=inspect.signature(cls).parameters
    assert list(params)==['upstream_origin','operator_token','mission_id','port','allow_messages','report_path']
    for name,default in [('port',0),('allow_messages',False),('report_path',None)]:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY and params[name].default==default
    for name in ['set_public_origin','revoke','serve_forever','shutdown','server_close']:
        assert callable(getattr(cls,name,None)),'missing public lifecycle method '+name
