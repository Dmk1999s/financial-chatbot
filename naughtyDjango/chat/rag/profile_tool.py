# chat/rag/profile_tool.py

from langchain.tools import Tool
from chat.gpt.session_store import get_session_data
from chat.constants.fields import QUESTION_KO


def get_profile_summary(query: str, session_id: str) -> str:
    """
    현재 세션에 저장된 사용자 프로필 정보를 요약하여 반환합니다.
    query 인자는 Tool 표준을 위해 받지만 사용하지 않습니다.
    """
    profile_data = get_session_data(session_id)
    if not profile_data:
        return "아직 수집된 사용자 정보가 없습니다."

    summary_lines = ["현재까지 수집된 사용자 정보는 다음과 같습니다:"]
    for key, question in QUESTION_KO.items():
        if key in profile_data and key != "_last_asked_key":
            value = profile_data[key]
            summary_lines.append(f"- {question.replace('알려주세요.', '')}: {value}")

    return "\n".join(summary_lines)


def create_profile_summary_tool(session_id: str) -> Tool:
    """세션 ID를 컨텍스트로 가지는 프로필 요약 Tool을 생성합니다."""

    # partial을 사용해 session_id를 함수에 미리 바인딩합니다.
    from functools import partial

    func = partial(get_profile_summary, session_id=session_id)

    return Tool(
        name="User Profile Summary",
        func=func,
        description="""
        # 사용해야 할 때:
        - 사용자가 챗봇에게 '자신이 입력한 정보', '내 정보', '내 프로필' 등을 기억하고 있는지 또는 알려달라고 질문할 때 사용합니다.
        - 예: "내가 알려준 정보 알아?", "내 투자 성향 뭐야?", "지금까지 입력한 내용 요약해줘"

        # 사용하면 안 될 때:
        - 금융 상품 추천 요청에는 절대로 사용하지 마세요.
        """
    )