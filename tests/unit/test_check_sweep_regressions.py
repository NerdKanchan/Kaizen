"""False-clearance and repeatability cases found during the code sweep."""

from decimal import Decimal

import pytest

from kaizen.checks.label_revision import ExpectedChange
from kaizen.ingest.quantity import parse_label_line
from kaizen.models import Classification, Severity
from kaizen.review.rundiff import _status
from tests.unit.test_bom_label_check import bom_doc, label_doc
from tests.unit.test_label_revision import run as revision
from tests.unit.test_pco_bom_check import by_key, pco_doc
from tests.unit.test_pco_bom_check import run as pco_check


@pytest.mark.parametrize('kind', ['ADD', 'SUBSTITUTE'])
def test_already_present_expected_change_checks_quantity(kind):
    old = label_doc([('End Cap', '1')])
    new = label_doc([('End Cap', '1')])
    expected = [ExpectedChange(kind, 'END CAP', quantity='2', old_description='Towel', source='PCO')]
    result = revision(old, new, expected)
    assert any(r.requires_validation and r.discrepancies for r in result)


def test_substitution_checks_quantity_even_when_description_is_expected():
    expected = [ExpectedChange('SUBSTITUTE', 'END CAP V2', quantity='2', old_description='END CAP', source='PCO')]
    result = revision(label_doc([('End Cap', '1')]), label_doc([('End Cap V2', '1')]), expected)
    assert any(r.discrepancies and r.requires_validation for r in result)
    correct = revision(label_doc([('End Cap', '1')]), label_doc([('End Cap V2', '2')]), expected)
    assert not any(r.discrepancies for r in correct)


def test_expectations_are_reusable_and_substitution_can_replace_unrelated_wording():
    old = label_doc([('Scissors', '1')])
    new = label_doc([('End Cap', '1')])
    expected = [ExpectedChange('SUBSTITUTE', 'END CAP', quantity='1', old_description='SCISSORS', source='PCO')]
    first, second = revision(old, new, expected), revision(old, new, expected)
    assert [r.model_dump() for r in first] == [r.model_dump() for r in second]
    assert not expected[0].consumed
    assert not any(r.discrepancies for r in first)


def test_unreadable_revision_is_blocked_and_missing_identity_never_clears():
    old, new = label_doc([('End Cap', '1')]), label_doc([('End Cap', '1')])
    new.header['unreadable_pages'] = [2]
    assert any(r.severity is Severity.BLOCKER for r in revision(old, new))
    del new.header['unreadable_pages']
    old.sku = new.sku = None
    assert revision(old, new)[0].severity is Severity.BLOCKER


@pytest.mark.parametrize('seq', ['', '7'])
def test_duplicate_substitution_rows_need_review(seq):
    pco = pco_doc(['A'], [('SUBSTITUTE', 'OLD', 'NEW', 'END CAP', '1', seq)])
    bom = bom_doc([('NEW', 'END CAP', '1'), ('NEW', 'END CAP', '1')], parent='A')
    bom.items[0].oper_seq = '7'
    bom.items[1].oper_seq = '7' if seq else '8'
    result = by_key(pco_check(pco, [bom]))[('A', 'SUBSTITUTE:OLD>NEW')]
    assert result.classification is Classification.POTENTIAL and result.requires_validation


def test_pco_cannot_confirm_a_deletion_against_incomplete_extraction():
    pco = pco_doc(['A'], [('DELETE', 'OLD', '', 'SCISSORS', '', '')])
    bom = bom_doc([('NEW', 'END CAP', '1')], parent='A')
    bom.header['unreadable_pages'] = [2]
    result = by_key(pco_check(pco, [bom]))[('A', 'DELETE:OLD')]
    assert result.requires_validation


def test_invalid_pco_numeric_text_cannot_clear_a_change():
    pco = pco_doc(['A'], [('ADD', '', 'NEW', 'END CAP', '1', '7')])
    pco.items[-1].attributes['qty_proposed'] = 'NaN'
    bom = bom_doc([('NEW', 'END CAP', '1')], parent='A')
    bom.items[0].oper_seq = '7'
    result = by_key(pco_check(pco, [bom]))[('A', 'ADD:NEW')]
    assert result.requires_validation and 'unreadable' in result.explanation


def test_diff_does_not_resolve_a_discrepancy_into_an_uncertain_pair():
    from tests.unit.test_bom_label_check import run
    before = next(r for r in run(bom_doc([('NEW', 'END CAP', '2')]), label_doc([('End Cap', '1')])) if r.discrepancies)
    after = before.model_copy(update={'classification': Classification.POTENTIAL, 'discrepancies': [], 'requires_validation': True})
    assert _status(before, after)[0] == 'still_open'


def test_zero_sub_quantity_preserves_source_text_without_crashing():
    line = parse_label_line('1 Each - End Cap (0 per)')
    assert line.quantity == Decimal(1)
    assert line.description == 'End Cap (0 per)' and line.sub_quantity is None
