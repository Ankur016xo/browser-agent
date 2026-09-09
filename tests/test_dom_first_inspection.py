from browser_agent.inspection import extract_structured_facts, inspect_requested_information


class FakePage:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def evaluate(self, _script):
        return self.snapshot


def test_extracts_key_value_facts_without_answer_database():
    snapshot = {
        "facts": [
            {"label": "Capital", "value": "Canberra", "source": "dom_table"},
            {"label": "Currency", "value": "Australian dollar", "source": "dom_table"},
        ],
        "jsonld": [],
        "body_text": "",
        "h1": "Australia",
        "title": "Australia - Wikipedia",
    }
    facts = extract_structured_facts(snapshot)
    assert {f["field"] for f in facts} == {"Capital", "Currency"}


def test_requested_information_uses_structured_dom_first():
    page = FakePage({
        "facts": [
            {"label": "Capital", "value": "Canberra", "source": "dom_table"},
            {"label": "Population", "value": "27,000,000", "source": "dom_table"},
            {"label": "Currency", "value": "Australian dollar", "source": "dom_table"},
        ],
        "jsonld": [],
        "body_text": "Population: 27,000,000",
        "h1": "Australia",
        "title": "Australia",
    })
    result = inspect_requested_information(page, ["capital", "population", "currency"])
    assert result["capital"] == "Canberra"
    assert result["population"] == "27,000,000"
    assert result["currency"] == "Australian dollar"


def test_does_not_take_unrelated_numbers_as_facts():
    page = FakePage({
        "facts": [],
        "jsonld": [],
        "body_text": "Welcome. 500 people viewed this page. 2026 update.",
        "h1": "Example",
        "title": "Example",
    })
    result = inspect_requested_information(page, ["price", "rating", "population"])
    assert result == {}


def test_jsonld_is_grounded_page_evidence():
    page = FakePage({
        "facts": [],
        "jsonld": ['{"name":"Example","founder":"Ada Lovelace","dateFounded":"1843"}'],
        "body_text": "",
        "h1": "Example",
        "title": "Example",
    })
    result = inspect_requested_information(page, ["founder", "date founded"])
    assert result["founder"] == "Ada Lovelace"
    assert result["date_founded"] == "1843"
