import pandas as pd
import streamlit as st

from keiba_engine import MissingInputFilesError, run_prediction_with_logs


st.set_page_config(
    page_title="競馬指数アプリ",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("競馬指数アプリ")

if "prediction_df" not in st.session_state:
    st.session_state.prediction_df = pd.DataFrame()
if "prediction_logs" not in st.session_state:
    st.session_state.prediction_logs = ""

if st.button("予想実行", type="primary", use_container_width=True):
    with st.spinner("予想を実行中..."):
        try:
            df, logs = run_prediction_with_logs()
            st.session_state.prediction_df = df
            st.session_state.prediction_logs = logs
            st.success("予想が完了しました。")
        except MissingInputFilesError as exc:
            st.session_state.prediction_df = pd.DataFrame()
            st.session_state.prediction_logs = ""
            missing = "\n".join(f"- {path}" for path in exc.missing_files)
            st.error(f"必要なCSVが足りません。\n\n{missing}")
        except Exception as exc:
            st.session_state.prediction_df = pd.DataFrame()
            st.session_state.prediction_logs = ""
            st.error(f"予想実行中にエラーが発生しました: {exc}")

st.subheader("実行ログ")
st.text_area(
    "log",
    value=st.session_state.prediction_logs,
    height=260,
    label_visibility="collapsed",
)

st.subheader("結果テーブル")
df = st.session_state.prediction_df
if df.empty:
    st.info("「予想実行」ボタンを押すと結果が表示されます。")
else:
    st.dataframe(df, use_container_width=True, hide_index=True)

    csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "CSVダウンロード",
        data=csv_bytes,
        file_name="keiba_prediction.csv",
        mime="text/csv",
        use_container_width=True,
    )
