import streamlit as st
import requests

st.set_page_config(page_title="Enterprise Knowledge Assistant", page_icon="📚", layout="wide")
st.title("📚 Enterprise AI Knowledge Assistant")
st.caption("Ask questions over organizational documents with role-aware retrieval and citations.")

with st.sidebar:
    st.header("Demo identity")
    api_url = st.text_input("API URL", "http://127.0.0.1:8000")
    user_id = st.text_input("User ID", "demo.user")
    roles_text = st.text_input("Roles", "employee")
    roles = [r.strip().lower() for r in roles_text.split(",") if r.strip()]
    st.divider()
    st.subheader("Upload document")
    uploaded = st.file_uploader("PDF, DOCX, TXT or XLSX", type=["pdf", "docx", "txt", "xlsx"])
    uploader = st.text_input("Uploaded by", user_id)
    allowed_roles = st.text_input("Allowed roles", "employee,hr")
    if st.button("Index document", disabled=uploaded is None, use_container_width=True):
        try:
            res = requests.post(
                f"{api_url}/documents/upload",
                files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")},
                data={"uploaded_by": uploader, "allowed_roles": allowed_roles}, timeout=180
            )
            if res.ok:
                st.success(res.json())
            else:
                st.error(res.text)
        except requests.RequestException as exc:
            st.error(str(exc))
    if st.button("Show indexed documents", use_container_width=True):
        try:
            st.json(requests.get(f"{api_url}/documents", timeout=20).json())
        except requests.RequestException as exc:
            st.error(str(exc))

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("Sources"):
                for source in msg["sources"]:
                    st.markdown(f"**{source['citation']} {source['filename']}** — chunk {source['chunk_index']}\\n\\n{source['excerpt']}")

question = st.chat_input("Ask a question about your documents...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            res = requests.post(
                f"{api_url}/chat",
                json={"question": question, "user_id": user_id, "roles": roles, "top_k": 5},
                timeout=120
            )
            res.raise_for_status()
            data = res.json()
            st.markdown(data["answer"])
            st.caption(f"Retrieved {data['retrieval_count']} passages · {data['mode']}")
            if data["sources"]:
                with st.expander("Sources and citations"):
                    for source in data["sources"]:
                        st.markdown(f"**{source['citation']} {source['filename']}** — chunk {source['chunk_index']} (distance {source['distance']})\\n\\n{source['excerpt']}")
            st.session_state.messages.append({"role": "assistant", "content": data["answer"], "sources": data["sources"]})
        except requests.RequestException as exc:
            st.error(f"Request failed: {exc}")
