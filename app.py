import streamlit as st
import pdfplumber
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import re
from pdf2image import convert_from_bytes
import pytesseract

# 1. KST 세팅 및 DB
kst = pytz.timezone('Asia/Seoul')
conn = sqlite3.connect('workers.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS approvals
             (company TEXT, name TEXT, status TEXT, date TEXT)''')
conn.commit()

def reset_old_records():
    now_kst = datetime.now(kst)
    today_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    c.execute("DELETE FROM approvals WHERE date < ?", (today_midnight.isoformat(),))
    conn.commit()

reset_old_records()

# 2. UI
st.title("안전관리: 작업자 4대 보험 출입 승인")
company = st.text_input("협력업체명")
name = st.text_input("작업자 성명")
uploaded_file = st.file_uploader("4대 보험 가입내역 확인서 (PDF)", type="pdf")

# 3. 검증 로직 (일반 추출 -> 실패 시 OCR 가동)
if st.button("가입 여부 확인 및 출입 승인"):
    if company and name and uploaded_file:
        try:
            today_str = datetime.now(kst).strftime('%Y-%m-%d')
            c.execute("SELECT * FROM approvals WHERE company=? AND name=? AND date LIKE ?", (company, name, f"{today_str}%"))
            if c.fetchone():
                st.warning(f"⚠️ {company} 소속 {name} 님은 오늘 이미 승인 완료된 인원입니다.")
            else:
                clean_company = re.sub(r'[\s\W_]+', '', company)
                clean_name = re.sub(r'[\s\W_]+', '', name)
                
                raw_text = ""
                # [1차 시도] 일반 전자문서 PDF 텍스트 추출 (빠름)
                with pdfplumber.open(uploaded_file) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            raw_text += text
                
                # [2차 시도] 백지상태(스캔본)로 판명되면 OCR 강제 가동
                if not raw_text.strip():
                    st.warning("🔄 스캔본(이미지) 문서가 감지되었습니다. 딥러닝 OCR(광학 문자 인식) 엔진을 가동합니다. (약 5~15초 소요)")
                    file_bytes = uploaded_file.getvalue()
                    images = convert_from_bytes(file_bytes)
                    for img in images:
                        # 한글 우선으로 이미지 속 글자를 강제로 뜯어냄
                        text = pytesseract.image_to_string(img, lang='kor')
                        raw_text += text
                
                clean_text = re.sub(r'[\s\W_]+', '', raw_text)
                
                # 디버그: OCR이 뜯어낸 글자 확인
                st.info("🔍 [디버그 모드] 시스템이 최종적으로 읽어낸 텍스트:")
                if clean_text:
                    st.code(clean_text)
                else:
                    st.error("🚨 텍스트 추출 실패: 서류의 화질이 너무 낮아 OCR 엔진으로도 해독할 수 없습니다.")
                
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

# 4. 명단 출력
st.subheader("금일 출입 승인 명단 (경비실 대조용)")
df = pd.read_sql_query("SELECT company as '업체명', name as '성명', status as '상태', date as '승인시간' FROM approvals", conn)
if not df.empty:
    df['승인시간'] = pd.to_datetime(df['승인시간']).dt.strftime('%H시 %M분')
    st.dataframe(df, use_container_width=True)
