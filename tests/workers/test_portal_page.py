from test_portal_gateway import feature

def test_mobile_memory_session_nonce_and_explicit_confirmations():
    page=feature('portal_page').PAGE
    for s in ('NONCE','width=device-width','allow_planning','allow_local_workers','approval_hash','crypto.randomUUID','AbortController','14000','UNKNOWN','STALE','textContent','/api/portal/state','/api/portal/logout'):
        assert s in page
    for s in ('localStorage','sessionStorage','document.cookie','innerHTML','/api/control','/api/chats','Bearer OPERATOR'):
        assert s not in page
    assert 'clearPrivate' in page and 'setInterval' not in page

# v2 human-readable single-capture rendering, source assertions only.
def test_graph_and_result_render_human_sections_not_default_json_walls():
    page=feature('portal_page').PAGE
    assert 'renderGraph' in page and 'renderResult' in page
    assert "show('graph',s)" not in page
    assert "show('result',side.status" not in page
    assert 'createElementNS' in page and 'depends_on' in page

# v3: refreshed login projects controller-owned unknown fencing.
def test_unknown_state_readback_fences_new_buttons():
    page=feature('portal_page').PAGE
    assert "state.mutation_status==='UNKNOWN'" in page
    assert "state.receipts" in page

# v4: actual engineering sidecar keeps its human statements under conclusion.
def test_actual_result_conclusion_and_report_auth_expiry_projection():
    page=feature('portal_page').PAGE
    assert 'v.conclusion?.statements' in page
    assert "clearPrivate();show('status','报告读取会话失效" in page
