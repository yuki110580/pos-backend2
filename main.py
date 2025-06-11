import os
from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel
from typing import List
from sqlalchemy import create_engine, text

# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# 購入リクエスト用のデータモデル
class PurchaseItem(BaseModel):
    prd_id: int
    prd_code: int
    prd_name: str
    prd_price: int

class PurchaseRequest(BaseModel):
    emp_cd: str
    store_cd: str
    pos_no: str
    items: List[PurchaseItem]


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
def read_root():
    return {"message": "Hello POS API!"}

# DB接続設定
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(
    DATABASE_URL,
    echo=True,
    connect_args={
        "ssl": {"ssl_mode": "REQUIRED"}
    }
)

@app.get("/item/{code}")
def get_item(code: int):
    query = text("SELECT PRD_ID, CODE, NAME, PRICE FROM product_master WHERE CODE = :code LIMIT 1")
    with engine.connect() as conn:
        result = conn.execute(query, {"code": code}).fetchone()
    
    if result:
        return {
            "prd_id": result[0],
            "code": result[1],
            "name": result[2],
            "price": result[3]
        }
    else:
        return None

# 購入処理
@app.post("/purchase")
def purchase(request: PurchaseRequest):
    TAX_RATE = 0.1  # 10% 税率

    with engine.begin() as conn:
        # ① transaction に仮INSERT（TOTAL=0）
        result = conn.execute(text("""
            INSERT INTO transaction (EMP_CD, STORE_CD, POS_NO, TOTAL_AMT, TTL_AMT_EX_TAX)
            VALUES (:emp_cd, :store_cd, :pos_no, 0, 0)
        """), {
            "emp_cd": request.emp_cd if request.emp_cd else "9999999999",
            "store_cd": request.store_cd,
            "pos_no": request.pos_no
        })

        # 新しい TRD_ID を取得
        trd_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()

        # ② transaction_detail に items をINSERT
        dtl_id = 1
        total_amount = 0

        for item in request.items:
            conn.execute(text("""
                INSERT INTO transaction_detail (TRD_ID, DTL_ID, PRD_ID, PRD_CODE, PRD_NAME, PRD_PRICE, TAX_CD)
                VALUES (:trd_id, :dtl_id, :prd_id, :prd_code, :prd_name, :prd_price, '10')
            """), {
                "trd_id": trd_id,
                "dtl_id": dtl_id,
                "prd_id": item.prd_id,
                "prd_code": item.prd_code,
                "prd_name": item.prd_name,
                "prd_price": item.prd_price
            })
            total_amount += item.prd_price
            dtl_id += 1

        # ③ 合計金額を税抜に計算
        total_amount_ex_tax = int(total_amount / (1 + TAX_RATE))

        # ④ transaction をUPDATE
        conn.execute(text("""
            UPDATE transaction
            SET TOTAL_AMT = :total_amt,
                TTL_AMT_EX_TAX = :total_amt_ex_tax
            WHERE TRD_ID = :trd_id
        """), {
            "total_amt": total_amount,
            "total_amt_ex_tax": total_amount_ex_tax,
            "trd_id": trd_id
        })

    # ⑤ レスポンス返却
    return {
        "success": True,
        "total_amount": total_amount,
        "total_amount_ex_tax": total_amount_ex_tax
    }

