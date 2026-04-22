import streamlit as st
import pdfplumber
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import re

# 1. 한국 시간대(KST) 및 데이터베이스 세팅
kst = pytz.timezone('Asia/Seoul')
conn = sqlite3.connect('workers.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS approvals
             (company TEXT, name TEXT, status TEXT, date TEXT)''')
conn.commit()

# 2. 매일 자정(KST) 이전 승인 기록 자동 초기화 함수
def reset_old_records():
    now_kst = datetime.now(kst)
    today_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    today_midnight_str = today_midnight.isoformat()
    c.execute("DELETE FROM approvals WHERE date < ?", (today_midnight_str,))
    conn.commit()

reset_old_records()

# 3. 화면 UI 구성
st.title("안전관리: 작업자 4대 보험 출입 승인")
st.write("작업자의 소속과 성명을 입력하고 서류를 업로드해 주세요.")

company = st.text_input("협력업체명 (예: 현텍)")
name = st.text_input("작업자 성명 (예: 박세용)")
uploaded_file = st.file_uploader("4대 보험 가입내역 확인서 (PDF)", type="pdf")

# 4. 검증 및 승인 로직
if st.button("가입 여부 확인 및 출입 승인"):
    if company and name and uploaded_file:
        try:
            # 중복 승인 확인 로직 (오늘 이미 승인된 사람인지 체크)
            today_str = datetime.now(kst).strftime('%Y-%m-%d')
            c.execute("SELECT * FROM approvals WHERE company=? AND name=? AND date LIKE ?", (company, name, f"{today_str}%"))
            if c.fetchone():
                st.warning(f"⚠️ {company} 소속 {name} 님은 오늘 이미 승인 완료된 인원입니다.")
            else:
                clean_company = re.sub(r'[\s\W_]+', '', company)
                clean_name = re.sub(r'[\s\W_]+', '', name)
                
                with pdfplumber.open(uploaded_file) as pdf:
                    raw_text = ""
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            raw_text += text
                
                clean_text = re.sub(r'[\s\W_]+', '', raw_text)
                
                if clean_company in clean_text and clean_name in clean_text:
                    st.success(f"✅ {company} 소속 {name} 님의 4대 보험 가입 서류가 정상 확인되었습니다.")
                    now_str = datetime.now(kst).isoformat()
                    c.execute("INSERT INTO approvals (company, name, status, date) VALUES (?, ?, ?, ?)", 
                              (company, name, "승인 완료", now_str))
                    conn.commit()
                else:
                    st.error("❌ 서류에서 입력하신 업체명이나 작업자 성명을 찾을 수 없습니다.")
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
    else:
        st.warning("협력업체명, 작업자 성명, PDF 파일을 모두 입력해 주세요.")

st.divider()

# 5. 경비실 대조용 대시보드 및 엑셀 다운로드
st.subheader("금일 출입 승인 명단 (경비실 대조용)")
df = pd.read_sql_query("SELECT company as '업체명', name as '성명', status as '상태', date as '승인시간' FROM approvals", conn)

if not df.empty:
    df['승인시간'] = pd.to_datetime(df['승인시간']).dt.strftime('%H시 %M분')
    st.dataframe(df, use_container_width=True)
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 오늘 명단 엑셀(CSV) 다운로드",
        data=csv,
        file_name=f"일일출입승인명단_{datetime.now(kst).strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
else:
    st.info("오늘 승인된 인원이 아직 없습니다.")
