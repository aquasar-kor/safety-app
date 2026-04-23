import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import re
import sqlite3
from google.cloud import vision
from google.oauth2 import service_account
import pdfplumber
from pdf2image import convert_from_bytes
import io

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

# 2. 구글 비전 API 열쇠 꽂기
creds_dict = dict(st.secrets["gcp_service_account"])
credentials = service_account.Credentials.from_service_account_info(creds_dict)
client = vision.ImageAnnotatorClient(credentials=credentials)

# 3. UI
st.title("안전관리: 작업자 4대 보험 출입 승인 (Google AI 탑재)")
company = st.text_input("협력업체명")
name = st.text_input("작업자 성명")
uploaded_file = st.file_uploader("4대 보험 가입내역 확인서 (PDF)", type=["pdf"])

# 4. 검증 로직
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

                with st.spinner('구글 AI가 서류를 정밀 분석 중입니다... (약 5~10초 소요)'):
                    # [1단계] PDF에서 일반 텍스트 추출 시도 (정상적인 전자문서인 경우)
                    with pdfplumber.open(uploaded_file) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                raw_text += text
                    
                    # [2단계] 백지(스캔본)인 경우 구글 Vision AI 가동
                    if not raw_text.strip():
                        st.warning("🔄 스캔본이 감지되어 구글 AI 비전 엔진을 가동합니다.")
                        file_bytes = uploaded_file.getvalue()
                        images = convert_from_bytes(file_bytes)
                        
                        for img in images:
                            img_byte_arr = io.BytesIO()
                            img.save(img_byte_arr, format='JPEG')
                            img_bytes = img_byte_arr.getvalue()
                            
                            # 구글 AI 눈알로 전송하여 텍스트 뜯어내기
                            vision_image = vision.Image(content=img_bytes)
                            response = client.text_detection(image=vision_image)
                            texts = response.text_annotations
                            if texts:
                                raw_text += texts[0].description
                
                clean_text = re.sub(r'[\s\W_]+', '', raw_text)
                
                # 구글 AI가 뽑아낸 텍스트 확인용
                st.info("🔍 [디버그] 구글 AI가 읽어낸 텍스트:")
                if clean_text:
                    st.code(clean_text)
                else:
                    st.error("🚨 텍스트 추출 실패: 서류 화질이 너무 낮습니다.")

                # 최종 판독
                if clean_company in clean_text and clean_name in clean_text:
                    st.success(f"✅ {company} 소속 {name} 님의 서류가 정상 확인되었습니다.")
                    now_str = datetime.now(kst).isoformat()
                    c.execute("INSERT INTO approvals (company, name, status, date) VALUES (?, ?, ?, ?)", 
                              (company, name, "승인 완료", now_str))
                    conn.commit()
                else:
                    st.error("❌ 서류 정보 불일치 (위쪽 디버그 창의 추출된 텍스트와 비교해 보세요)")
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
    else:
        st.warning("협력업체명, 작업자 성명, PDF 파일을 모두 입력해 주세요.")

st.divider()
st.subheader("금일 출입 승인 명단 (경비실 대조용)")
df = pd.read_sql_query("SELECT company as '업체명', name as '성명', status as '상태', date as '승인시간' FROM approvals", conn)
if not df.empty:
    df['승인시간'] = pd.to_datetime(df['승인시간']).dt.strftime('%H시 %M분')
    st.dataframe(df, use_container_width=True)
