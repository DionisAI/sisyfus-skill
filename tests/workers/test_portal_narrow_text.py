"""Frozen CSS seam for the actual 360px long-receipt overflow, not device proof."""
import hashlib
import re

from sisyfus.workers.portal_page import PAGE


def test_portal_main_inherits_anywhere_wrap_for_receipt_and_inbox_text():
    style = re.search(r'<style nonce="NONCE">(.*?)</style>', PAGE, re.S).group(1)
    main_rule = re.search(r'(?:^|\})main\{([^}]*)\}', style).group(1)
    assert re.search(r'(?:^|;)overflow-wrap\s*:\s*anywhere\s*(?:;|$)', main_rule), (
        'Unbroken evidence hashes in result p and inbox div must inherit wrapping')


def test_portal_does_not_conceal_horizontal_overflow_instead_of_wrapping():
    style = re.search(r'<style nonce="NONCE">(.*?)</style>', PAGE, re.S).group(1)
    assert not re.search(r'overflow(?:-x)?\s*:\s*(?:hidden|clip)', style)


def test_portal_wrap_microstep_preserves_all_existing_page_javascript():
    script = re.search(r'<script nonce="NONCE">(.*?)</script>', PAGE, re.S).group(1)
    assert hashlib.sha256(script.encode()).hexdigest() == '19794b4b5a12b19da172b37d809bbbc6b9d01734921d863c3bed6350f857fefc'
