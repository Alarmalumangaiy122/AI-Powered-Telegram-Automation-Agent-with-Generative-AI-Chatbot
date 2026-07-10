import streamlit as st
from groq import Groq
from dotenv import load_dotenv
import os
import time

# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(
    page_title="Aria AI Assistant",
    page_icon="✦",
    layout="centered"
)

# -----------------------------
# CSS
# -----------------------------
st.markdown("""
<style>

.stApp{
    background:#0c0c10;
}

.block-container{
    max-width:850px;
    padding-top:20px;
}

h1{
    color:white;
    text-align:center;
}

.subtitle{
    color:#8b8ba5;
    text-align:center;
    margin-bottom:25px;
}

.user{
    background:#7c4dff;
    color:white;
    padding:12px;
    border-radius:15px;
    margin-top:10px;
    margin-left:120px;
}

.bot{
    background:#1b1b23;
    color:white;
    padding:12px;
    border-radius:15px;
    margin-top:10px;
    margin-right:120px;
    border:1px solid #333;
}

</style>
""", unsafe_allow_html=True)

# -----------------------------
# API
# -----------------------------
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error(" GROQ_API_KEY not found in .env file")
    st.stop()

client = Groq(api_key=GROQ_API_KEY)

MODELS = {
    "Llama 3.3 70B":"llama-3.3-70b-versatile",
    "Llama3 70B":"llama3-70b-8192",
    "Llama3 8B":"llama3-8b-8192",
    "Mixtral":"mixtral-8x7b-32768",
    "Gemma2":"gemma2-9b-it"
}

SYSTEM_PROMPT="""
You are Aria.

You are a professional AI assistant.

Answer clearly.

Use markdown.

Be friendly.
"""

# -----------------------------
# SESSION
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages=[]

# -----------------------------
# HEADER
# -----------------------------
st.markdown("<h1>✦ Aria AI Assistant</h1>",unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Powered by Groq</div>",unsafe_allow_html=True)

# -----------------------------
# MODEL
# -----------------------------
selected=st.selectbox(
    "Choose Model",
    list(MODELS.keys())
)

model=MODELS[selected]

# -----------------------------
# CLEAR
# -----------------------------
if st.button("🗑 Clear Chat"):

    st.session_state.messages=[]

    st.rerun()

st.divider()

# -----------------------------
# SUGGESTIONS
# -----------------------------
if len(st.session_state.messages)==0:

    c1,c2,c3=st.columns(3)

    with c1:

        if st.button("Explain AI"):

            st.session_state.prefill="Explain Artificial Intelligence"

            st.rerun()

    with c2:

        if st.button("Python Code"):

            st.session_state.prefill="Write Python code"

            st.rerun()

    with c3:

        if st.button("Resume Help"):

            st.session_state.prefill="Help improve my resume"

            st.rerun()

# -----------------------------
# CHAT HISTORY
# -----------------------------
for m in st.session_state.messages:

    if m["role"]=="user":

        st.markdown(
            f"<div class='user'>{m['content']}</div>",
            unsafe_allow_html=True
        )

    else:

        st.markdown(
            f"<div class='bot'>{m['content']}</div>",
            unsafe_allow_html=True
        )

# -----------------------------
# INPUT
# -----------------------------
default=""

if "prefill" in st.session_state:

    default=st.session_state.prefill

    del st.session_state.prefill

prompt=st.chat_input(
    "Message Aria..."
)

if prompt:

    st.session_state.messages.append(
        {
            "role":"user",
            "content":prompt
        }
    )

    history=[]

    history.append(
        {
            "role":"system",
            "content":SYSTEM_PROMPT
        }
    )

    for msg in st.session_state.messages:

        history.append(
            {
                "role":msg["role"],
                "content":msg["content"]
            }
        )

    with st.spinner("Thinking..."):

        start=time.time()

        response=client.chat.completions.create(

            model=model,

            messages=history,

            temperature=0.7,

            max_tokens=1024

        )

        answer=response.choices[0].message.content

        elapsed=time.time()-start

    st.session_state.messages.append(

        {
            "role":"assistant",
            "content":answer
        }

    )

    st.success(f"Response generated in {elapsed:.2f} seconds")

    st.rerun()

st.divider()

st.caption("✦ Aria AI Assistant | Powered by Groq")