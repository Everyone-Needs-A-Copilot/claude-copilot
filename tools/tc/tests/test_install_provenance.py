"""Receipts cannot silently repair missing or changed installations."""
import pytest
from tc import provenance
from tc.db.exceptions import ValidationError


def test_receipt_creation_and_verification_are_separate(tmp_path, monkeypatch):
    receipt = tmp_path / 'tc-provenance.json'
    monkeypatch.setattr(provenance, 'receipt_path', lambda: receipt)
    state = {'mode': 'development', 'version': 'fixture', 'source_commit': 'a'*40, 'source_tree': 'b'*40, 'files': {'module.py': 'hash'}, 'capabilities': ['check-qa', 'contract', 'evidence-identity']}
    monkeypatch.setattr(provenance, 'capture', lambda: dict(state))
    with pytest.raises(ValidationError, match='missing'):
        provenance.verify()
    assert not receipt.exists()
    assert provenance.record()['verified']
    assert receipt.exists()
    before = receipt.read_bytes()
    state['files'] = {'module.py': 'changed'}
    with pytest.raises(ValidationError, match='differs'):
        provenance.verify()
    assert receipt.read_bytes() == before


def test_receipt_symlink_is_rejected(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    outside.write_text('preserve')
    receipt = tmp_path / 'tc-provenance.json'
    receipt.symlink_to(outside)
    monkeypatch.setattr(provenance, 'receipt_path', lambda: receipt)
    with pytest.raises(ValidationError, match='symlink'):
        provenance.record()
    assert outside.read_text() == 'preserve'
