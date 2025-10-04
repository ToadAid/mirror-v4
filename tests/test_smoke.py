from tobyworld_v4.core.v4 import Guide, Retriever, Synthesis, Resonance, Lucidity, Ledger, RunCtx, config
def test_pipeline_smoke():
    guide = Guide(config); retriever = Retriever(config)
    synthesis = Synthesis(config); resonance = Resonance(config)
    lucidity = Lucidity(config); ledger = Ledger(config)
    q = "What is the Leaf of Yield?"
    ctx = RunCtx(user={"id":"qa"}, query=q)
    g = guide.guard(q, {"id":"qa"}); ctx.intent = g["intent"]; ctx.refined_query = g["refined_query"]
    r = retriever.multi_arc(ctx.refined_query or q, g["hint"])
    text, trace = synthesis.weave(r); h = resonance.score(text, r)
    final = lucidity.distill(text)
    assert isinstance(final.get("sage",""), str)
