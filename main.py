from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
from typing import List, Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("geopark_key.json", scope)
    return gspread.authorize(creds)

class RecordData(BaseModel):
    name: str; island: str; role: str; action: str; location: str; action_time: str 

class OperationData(BaseModel):
    name: str; island: str; role: str; target_time: str; visitors: int; listeners: int; count: int; co_commentary: str; remarks: str; log_location: str 

class PlanDataBulk(BaseModel):
    name: str; island: str; plans: List[Dict] 

class PlanChangeData(BaseModel):
    name: str; island: str; target_date: str; change_type: str; change_detail: str; target_guide: str

class ApprovalData(BaseModel):
    sheet_name: str; row_index: int; status: str

@app.post("/login")
async def login(data: dict):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("사용자")
        users = sh.get_all_records()
        found = next((u for u in users if str(u['아이디']) == data.get('uid') and str(u['비번']) == data.get('upw')), None)
        if found: return {"status": "ok", "name": found['이름'], "role": found['직책'], "island": found['섬']}
        else: raise HTTPException(status_code=401, detail="정보 불일치")
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/record")
async def record_action(data: RecordData):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("활동일지(NEW)")
        seoul_tz = pytz.timezone('Asia/Seoul')
        now = datetime.now(seoul_tz)
        date_str = now.strftime('%Y-%m-%d'); timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        time_str = data.action_time + ":00" if len(data.action_time) == 5 else data.action_time
        if data.action == "출근":
            sh.append_row([date_str, data.island, data.location, data.name, time_str, "", timestamp, now.year, now.month])
        elif data.action == "퇴근" or data.action == "이동":
            records = sh.get_all_records()
            for i, row in enumerate(reversed(records)):
                if row.get('이름') == data.name and row.get('날짜') == date_str and not row.get('퇴근시간'):
                    row_idx = len(records) - i + 1
                    sh.update_cell(row_idx, 6, time_str)
                    if data.action == "이동":
                        sh.append_row([date_str, data.island, data.location, data.name, time_str, "", timestamp, now.year, now.month])
                    break
        return {"status": "ok"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/log_operation")
async def log_operation(data: OperationData):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("운영일지(NEW)")
        seoul_tz = pytz.timezone('Asia/Seoul')
        now = datetime.now(seoul_tz)
        row = [now.strftime('%Y-%m-%d'), data.island, data.log_location, data.name, data.target_time, data.visitors, data.listeners, data.count, data.remarks, data.co_commentary, now.strftime('%Y-%m-%d %H:%M:%S'), now.year, now.month]
        sh.append_row(row)
        return {"status": "ok"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/check_co_status")
async def check_co_status(name: str, target_time: str):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("운영일지(NEW)")
        records = sh.get_all_records()
        today = datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d')
        already = next((r for r in records if str(r.get('날짜')) == today and str(r.get('이름')) == name and str(r.get('입력시간')) == target_time), None)
        if already: return {"status": "already_logged"}
        designated = next((r for r in records if str(r.get('날짜')) == today and str(r.get('입력시간')) == target_time and str(r.get('공동해설')) == name), None)
        if designated: return {"status": "designated", "designated_by": str(designated.get('이름'))}
        return {"status": "none"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/active_guides")
async def get_active_guides(location: str, name: str):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("활동일지(NEW)")
        records = sh.get_all_records()
        today_str = datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d')
        active_users = list(set([str(row.get('이름')) for row in records if str(row.get('날짜')) == today_str and str(row.get('장소')) == location and str(row.get('이름')) != name]))
        return {"status": "ok", "guides": active_users}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/submit_plan_bulk")
async def submit_plan_bulk(data: PlanDataBulk):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("활동계획서(NEW)")
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        rows = [[p['plan_date'], data.island, p['location'], data.name, p['activity_status'], p['remarks'], timestamp, now.year, now.month, p.get('status', '대기중'), "", ""] for p in data.plans]
        sh.append_rows(rows)
        return {"status": "ok"}
    except Exception as e: 
        print("Bulk Plan Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_guides")
async def get_guides(island: str, exclude_name: str):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("사용자")
        users = sh.get_all_records()
        guides = [str(u['이름']) for u in users if str(u['섬']) == island and str(u['이름']) != exclude_name and str(u['직책']) in ['해설사', '조장']]
        return {"status": "ok", "guides": guides}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/request_plan_change")
async def request_plan_change(data: PlanChangeData):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet("활동계획_변경신청")
        timestamp = datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S')
        status = "대타승인대기" if data.change_type == "해설사 변경(대타)" else "조장승인대기"
        sh.append_row([timestamp, data.name, data.island, data.target_date, data.change_type, data.change_detail, data.target_guide, status])
        return {"status": "ok"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_pending_requests")
async def get_pending_requests(island: str):
    try:
        client = get_gsheet_client()
        db = client.open("지질공원_운영일지_DB")
        
        plan_sh = db.worksheet("활동계획서(NEW)")
        all_plans = plan_sh.get_all_records()
        pending_plans = []
        for i, r in enumerate(all_plans):
            if str(r.get('섬')) == island and "대기" in str(r.get('상태', '')):
                r['row_index'] = i + 2
                pending_plans.append(r)
        
        change_sh = db.worksheet("활동계획_변경신청")
        all_changes = change_sh.get_all_records()
        pending_changes = []
        for i, r in enumerate(all_changes):
            if str(r.get('섬')) == island and str(r.get('승인상태', '')) == "조장승인대기":
                r['row_index'] = i + 2
                pending_changes.append(r)
                
        return {"status": "ok", "plans": pending_plans, "changes": pending_changes}
    except Exception as e: 
        print("Get Pending Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process_approval")
async def process_approval(data: ApprovalData):
    try:
        client = get_gsheet_client()
        sh = client.open("지질공원_운영일지_DB").worksheet(data.sheet_name)
        col_idx = 10 if data.sheet_name == "활동계획서(NEW)" else 8
        sh.update_cell(data.row_index, col_idx, data.status)
        return {"status": "ok"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))