"""RAGAS metrics over collected repair records, judged by Gemini.

Faithfulness: are diagnosis statements entailed by retrieved evidence?
LLMContextPrecisionWithoutReference: is the retrieved evidence relevant to the diagnosis?
AspectCritic (x2): diagnosis addresses the reproduced failures; patch stays within scope.
ResponseRelevancy needs embeddings and is only run when RAGAS_EMBEDDINGS=1.
"""
import os


def run(records):
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AspectCritic, Faithfulness, LLMContextPrecisionWithoutReference
    from langchain_google_genai import ChatGoogleGenerativeAI
    key = os.getenv('JUDGE_API_KEY') or os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not key:
        raise RuntimeError('GEMINI_API_KEY (or JUDGE_API_KEY) is not set')
    llm = LangchainLLMWrapper(ChatGoogleGenerativeAI(model=os.getenv('JUDGE_MODEL', 'gemini-2.5-pro'), google_api_key=key, temperature=0))
    samples = [SingleTurnSample(user_input=r['task'], retrieved_contexts=r['contexts'], response=r['diagnosis'] + '\n\nPatch:\n' + r['patch']) for r in records]
    metrics = [
        Faithfulness(llm=llm),
        LLMContextPrecisionWithoutReference(llm=llm),
        AspectCritic(name='addresses_failures', llm=llm, definition='Does the response diagnose the reproduced test failures that appear in the retrieved contexts?'),
        AspectCritic(name='scope_discipline', llm=llm, definition='Does the patch change only code needed for the dependency incompatibility, with no tests edited, no new network/shell use?'),
    ]
    if os.getenv('RAGAS_EMBEDDINGS') == '1':
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.metrics import ResponseRelevancy
        emb = LangchainEmbeddingsWrapper(GoogleGenerativeAIEmbeddings(model=os.getenv('RAGAS_EMBED_MODEL', 'models/gemini-embedding-001'), google_api_key=key))
        metrics.append(ResponseRelevancy(llm=llm, embeddings=emb))
    frame = evaluate(EvaluationDataset(samples=samples), metrics=metrics, show_progress=False).to_pandas()
    rows = [{'id': r['id'], **{c: (None if v != v else float(v)) for c, v in frame.iloc[i].items() if c not in ('user_input', 'retrieved_contexts', 'response')}} for i, r in enumerate(records)]
    cols = [c for c in rows[0] if c != 'id'] if rows else []
    means = {c: (lambda xs: sum(xs) / len(xs) if xs else None)([r[c] for r in rows if r[c] is not None]) for c in cols}
    return {'metrics': means, 'rows': rows}
