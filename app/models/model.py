import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler

# 데이터 로드 함수
def load_data(file_path):
    """
    CSV 데이터를 로드하고 필요한 컬럼이 모두 존재하는지 확인.
    """
    data = pd.read_csv(file_path)
    required_columns = ['RDS_RG', 'ROAD_NAME', 'RD_SLOPE', 'ACC_OCC', 'ACC_SC']
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"Missing required column: {col}")
    return data

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