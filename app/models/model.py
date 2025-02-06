import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler
from app.database.mysql_connect import get_connection
from mysql.connector import Error
from fastapi import HTTPException

# 데이터 로드 함수
def get_road_info(region: str):
    """Fetch road information from the road_info table for a given region."""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT road_id, rds_id, road_cd, road_name, sig_cd, rds_rg, wdr_rd_cd, 
                   rbp, rep, rd_slope, acc_occ, acc_sc 
            FROM road_info 
            WHERE rds_rg = %s
        """
        cursor.execute(query, (region,))
        roads = cursor.fetchall()

        if not roads:
            raise HTTPException(status_code=404, detail=f"No road data found for region '{region}'.")

        return roads

    except Error as e:
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Database query failed.")

    finally:
        if "cursor" in locals() and cursor:
            cursor.close()
        if "connection" in locals() and connection.is_connected():
            connection.close()

# 모델 학습 함수
def train_model(data):
    """
    데이터로 모델을 학습하고 예측 점수를 계산.
    """
    # 입력 변수와 타겟 변수 정의
    X = data[['RD_SLOPE', 'ACC_OCC', 'ACC_SC']]
    y = (data['ACC_OCC'] * 3) + (data['ACC_SC'] * 3) + (data['RD_SLOPE'] * 4)

    # 데이터 스케일링
    scaler = MinMaxScaler()
    X_scaled = scaler.fit_transform(X)

    # 모델 학습
    model = RandomForestRegressor(random_state=42)
    model.fit(X_scaled, y)

    # 예측 점수 계산
    data['예측점수'] = model.predict(X_scaled)

    return data, model, scaler  # 데이터, 학습된 모델, 스케일러 반환