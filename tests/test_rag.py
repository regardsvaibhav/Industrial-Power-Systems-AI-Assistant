from app.rag.generate import extractive_answer, label_sources
from app.rag.grounding import check_grounding


def test_retrieval_finds_relevant_page(store, assistant):
    hits = store.search("What is the polarization index?", k=3)
    assert hits[0].metadata["title"].startswith("IPS-07")
    assert hits[0].metadata["page"] == 2


def test_metadata_filter_restricts_documents(store, assistant):
    docs = {d["title"].split()[0]: d["doc_id"] for d in store.list_documents()}
    hits = store.search("power factor correction capacitors", k=5, doc_ids=[docs["IPS-03"]])
    assert hits and all(h.metadata["doc_id"] == docs["IPS-03"] for h in hits)


def test_hybrid_and_semantic_scores(store, assistant):
    h = store.search("ONAF cooling fans", k=3, hybrid=True)
    assert h[0].metadata["title"].startswith("IPS-03")
    s = store.search("ONAF cooling fans", k=3, hybrid=False)
    assert all(x.score == x.semantic for x in s)


def test_answer_has_real_page_citations(assistant):
    r = assistant.ask("What is the polarization index?")
    assert r.status == "answered"
    assert r.citations
    c = r.citations[0]
    assert c.title.startswith("IPS-07") and c.page == 2
    assert "polarization index" in c.snippet.lower()
    # every [S#] marker in the answer refers to a returned citation
    import re

    assert set(re.findall(r"\[(S\d+)\]", r.answer)) <= {x.id for x in r.citations}
    assert r.grounding.score == 1.0


def test_abstains_on_off_topic_question(assistant):
    r = assistant.ask("Who won the 2018 football world cup?")
    assert r.status == "abstained"
    assert not r.citations


def test_abstains_when_named_entity_missing(assistant):
    r = assistant.ask("What does IEEE 1584 specify for arc flash calculations?")
    assert r.status == "abstained"


def test_vague_question_asks_for_clarification(assistant):
    assert assistant.ask("What is the limit?").status == "needs_clarification"


def test_calculation_routed_to_tool(assistant):
    r = assistant.ask("Calculate the real power of a 400 V three-phase motor drawing 100 A at 0.85 power factor")
    assert r.status == "calculation"
    assert r.calculation.tool == "three_phase_power"
    assert r.calculation.outputs["real_power"].value == 58.89


def test_calculation_missing_input_requests_clarification(assistant):
    r = assistant.ask("Calculate the power of a 400 V motor drawing 30 A")
    assert r.status == "needs_clarification"
    assert "power_factor" in r.missing_inputs


def test_grounding_flags_invented_numbers():
    src = {"S1": "Typical droop setting is 4 to 5 percent for governors."}
    good = check_grounding("Typical droop setting is 4 to 5 percent for governors. [S1]", src)
    bad = check_grounding("Typical droop setting is 12.5 percent for governors. [S1]", src)
    assert good.score == 1.0
    assert bad.score == 0.0 and "12.5" in bad.unsupported_numbers


def test_extractive_answer_only_copies_source_sentences(store, assistant):
    hits = store.search("Why is low power factor penalised by utilities?", k=3)
    sources = label_sources(hits)
    texts = {k: v.text for k, v in sources.items()}
    gen = extractive_answer("Why is low power factor penalised by utilities?", sources, texts, store.embed)
    assert not gen.abstain
    import re

    for sent in re.split(r" \[S\d+\] ?", gen.answer):
        if sent.strip():
            assert any(sent.strip() in t for t in texts.values())
