import os
import json
from openai import OpenAI
from chat.opensearch_client import OPENSEARCH_CLIENT as os_client

# 1. 모든 테이블의 전체 컬럼 정보를 상세하게 정의
SCHEMA_DEFS = {
    "deposit": {
        "kor_co_nm": "금융 회사명",
        "fin_prdt_nm": "예금 상품명",
        "mtrt_int": "만기 후 이자 계산 방식",
        "spcl_cnd": "특별 우대 조건",
        "join_member": "가입 대상",
        "join_way": "가입 방법",
        "etc_note": "기타 참고사항"
    },
    "savings": {
        "kor_co_nm": "금융 회사명",
        "fin_prdt_nm": "적금 상품명",
        "mtrt_int": "만기 후 이자 계산 방식",
        "spcl_cnd": "특별 우대 조건",
        "join_member": "가입 대상",
        "join_way": "가입 방법",
        "etc_note": "기타 참고사항"
    },
    "annuity": {
        "kor_co_nm": "운용 회사명",
        "fin_prdt_nm": "연금 상품명",
        "pnsn_kind_nm": "연금 종류",
        "prdt_type_nm": "상품 유형",
        "avg_prft_rate": "평균 수익률 (%)",
        "btrm_prft_rate1": "전년도 수익률 (%)",
        "guar_rate": "최저 보증 이율",
        "sale_co": "판매사",
        "join_way": "가입 방법",
        "sale_strt_day": "판매 시작일"
    },
    "krx_stock_info": {
        "bstp_kor_isnm": "한글 종목명",
        "prdt_abrv_name": "종목 약식명",
        "stck_shrn_iscd": "종목 코드",
        "stck_prpr": "현재가",
        "per": "주가수익비율 (PER)",
        "pbr": "주가순자산비율 (PBR)",
        "eps": "주당순이익 (EPS)"
    },
    "nasdaq_stock_info": {
        "prdt_abrv_name": "종목 약식명",
        "code": "종목 코드 (티커)",
        "last": "현재가",
        "perx": "주가수익비율 (PER)",
        "pbrx": "주가순자산비율 (PBR)",
        "epsx": "주당순이익 (EPS)",
        "e_icod": "업종 (섹터)"
    }
}


def parse_query_with_llm(query: str, openai_client: OpenAI) -> dict:
    """사용자의 자연어 질문을 분석하여 필터 및 정렬 조건이 포함된 JSON 쿼리로 변환합니다."""

    parser_prompt = f"""
    사용자의 질문을 분석하여 OpenSearch에서 사용할 JSON 객체로 변환해라.

    [규칙]
    1.  `semantic_query`에는 사용자의 핵심 의도를 요약한 검색어를 넣어라.
    2.  `filters`에는 숫자/카테고리에 대한 명확한 조건만 추출하여 배열로 넣어라.
    3.  **정렬 규칙**: "가장 높은", "가장 큰" 등은 `desc` (내림차순)로, "가장 낮은", "가장 작은" 등은 `asc` (오름차순)로 `sort` 객체를 생성해라. 정렬 조건이 없으면 `sort` 필드는 생략한다.
    4.  **금융 용어 해석**: "저평가된 PBR"은 PBR이 1 미만인 조건으로 변환한다.
    5.  **필드명 정규화**: `pbrx`는 `pbr`로, `perx`는 `per`로 정규화한다.
    6.  오직 JSON 객체만 반환하고 다른 설명은 절대 추가하지 마라.

    [예시 1]
    질문: "pbr이 가장 높은 주식을 알려줘"
    결과:
    {{
      "semantic_query": "가장 높은 PBR 주식",
      "filters": [],
      "sort": {{ "field": "pbr", "order": "desc" }}
    }}

    [예시 2]
    질문: "PER이 10 미만이고 저평가된 주식 찾아줘"
    결과:
    {{
      "semantic_query": "저평가된 저PER 주식",
      "filters": [
        {{ "field": "per", "operator": "lt", "value": 10 }},
        {{ "field": "pbr", "operator": "lt", "value": 1 }}
      ]
    }}
    ---
    [사용자 질문]
    {query}
    """

    response = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": parser_prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    try:
        return json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, IndexError):
        return {"semantic_query": query, "filters": []}


def recommend_with_knn(query: str, top_k: int = 3, index_name: str = None) -> str:
    openai = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    index = index_name or os.getenv('OPENSEARCH_INDEX', 'financial-products')

    # 1. LLM으로 사용자 질문을 구조화된 쿼리(필터+정렬)로 변환
    structured_query = parse_query_with_llm(query, openai)
    print("\n--- LLM 파서 결과 ---")
    print(json.dumps(structured_query, indent=2, ensure_ascii=False))
    semantic_query = structured_query.get("semantic_query", query)
    filters = structured_query.get("filters", [])
    sort_order = structured_query.get("sort")  # 정렬 조건 추출

    # 2. OpenSearch 쿼리 동적 생성
    os_filters = []
    # (os_filters 생성 로직은 이전과 동일)

    body = {}
    if sort_order and sort_order.get("field"):
        # 정렬 요청이 있을 경우: 일반 검색 + 정렬
        sort_field = sort_order["field"]
        sort_field_variants = [sort_field]  # pbr, per 등 정규화된 필드
        if sort_field == "pbr": sort_field_variants.append("pbrx")
        if sort_field == "per": sort_field_variants.append("perx")

        body = {
            "size": top_k,
            "query": {"bool": {"filter": os_filters}} if os_filters else {"match_all": {}},
            "sort": [
                # 여러 필드 중 하나라도 값이 있으면 그 값을 기준으로 정렬
                {f: {"order": sort_order["order"], "missing": "_last"} for f in sort_field_variants}
            ]
        }
    else:
        # 정렬 요청이 없을 경우: k-NN 하이브리드 검색 (기존 방식)
        emb = openai.embeddings.create(model='text-embedding-3-small', input=[semantic_query]).data[0].embedding
        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [{"knn": {"embedding": {"vector": emb, "k": top_k}}}],
                    "filter": os_filters
                }
            }
        }

    # 3. 검색 실행 및 4. 최종 답변 생성
    hits = os_client.search(index=index, body=body)['hits']['hits']

    # 4. 최종 답변 생성
    payload = []
    tables_in_result = set()
    for h in hits:
        source = h["_source"]
        payload.append(source)
        tables_in_result.add(source.get("table"))

    schema_explanation = ""
    for table_name in sorted(list(tables_in_result)):
        if table_name in SCHEMA_DEFS:
            schema_explanation += f"--- [{table_name} 컬럼 설명] ---\n"
            for col, desc in SCHEMA_DEFS[table_name].items():
                schema_explanation += f"- `{col}`: {desc}\n"
            schema_explanation += "\n"

    RAG_PROMPT_TEMPLATE = """
    당신은 '챗봇'이라는 이름을 가진 전문 금융 상품 분석가입니다. 당신의 임무는 주어진 [컬럼 설명]과 [검색된 데이터]만을 사용하여 사용자의 [요청 질문]에 대한 맞춤형 답변을 생성하는 것입니다.

    [엄격한 규칙]
    1.  **데이터 기반 답변**: 당신의 답변은 **오직 [검색된 데이터]에서만** 나와야 합니다. 데이터에 없는 내용은 절대로 언급하거나 추측하지 마십시오.
    2.  **컬럼 의미 활용**: [컬럼 설명]을 참고하여 데이터의 각 필드가 무엇을 의미하는지 정확히 해석하고, 이 의미를 답변에 명확하게 반영해야 합니다.
    3.  **정보 부족 시 대응**: 만약 [검색된 데이터]에 [요청 질문]에 답할 만한 정보가 없다면, "죄송하지만, 문의하신 내용에 대해 정확한 정보를 찾을 수 없었습니다." 라고만 답변하세요.

    ---
    [컬럼 설명]
    {schema_explanation}
    ---
    [검색된 데이터]
    {context}
    ---
    [요청 질문]
    {question}
    ---
    [맞춤형 답변]
    """
    context_str = json.dumps(payload, ensure_ascii=False, indent=2)
    final_prompt = RAG_PROMPT_TEMPLATE.format(
        schema_explanation=schema_explanation,
        context=context_str,
        question=query
    )

    chat = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.2,
        max_tokens=2000,
    )
    return chat.choices[0].message.content