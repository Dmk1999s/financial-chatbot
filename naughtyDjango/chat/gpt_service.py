import uuid
from openai import OpenAI
from dotenv import load_dotenv
import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"
store = {}

def get_session_id(request_data):
    return request_data.get("session_id", str(uuid.uuid4()))

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def convert_history_to_openai_format(history):
    role_map = {"human": "user", "ai": "assistant", "system": "system"}
    return [{"role": role_map.get(msg.type, msg.type), "content": msg.content} for msg in history]

def run_gpt(input_data, config):
    user_input = input_data["input"]

    session_id = config.get("configurable", {}).get("session_id")
    history = get_session_history(session_id).messages
    formatted_history = convert_history_to_openai_format(history)

    response = client.chat.completions.create(
        model=fine_tuned_model,
        messages=formatted_history + [{"role": "user", "content": user_input}]
    )
    return {"output": response.choices[0].message.content}


# Runnable 구성
runnable = RunnableLambda(run_gpt)

with_message_history = RunnableWithMessageHistory(
    runnable,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history"
)

# 외부에 제공할 함수
def handle_chat(user_input, session_id):
    result = with_message_history.invoke(
        {"input": user_input},
        config={"configurable": {"session_id": session_id}}
    )
    return result["output"], session_id