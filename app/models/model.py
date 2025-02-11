import pickle
import numpy as np
import joblib
import pandas as pd

# 모델과 스케일러 로드 함수
import os

def load_model(model_path=None, scaler_path=None):
    base_dir = os.path.dirname(os.path.abspath(__file__))  # 현재 파일(model.py)의 경로
    
    if model_path is None:
        model_path = os.path.join(base_dir, "rf_model_best.pkl")
    if scaler_path is None:
        scaler_path = os.path.join(base_dir, "rf_scaler_best.pkl")
    try:
        with open(model_path, 'rb') as f:
            model = joblib.load(f)
        with open(scaler_path, 'rb') as f:
            scaler = joblib.load(f)
        print("모델과 스케일러가 성공적으로 로드되었습니다.")
        return model, scaler
    except FileNotFoundError:
        raise Exception("모델 또는 스케일러 파일을 찾을 수 없습니다.")

# 예측 함수
def predict(model, scaler, input_data):
    try:
        # 입력 데이터를 DataFrame으로 변환 (배열 입력 지원)
        X_input = pd.DataFrame(input_data, columns=scaler.feature_names_in_)
        
        # 스케일 변환 (벡터 연산)
        X_scaled = scaler.transform(X_input)

        # 모델 예측 (배치 예측 지원)
        predictions = model.predict(X_scaled)

        return predictions.tolist()  # 리스트 형태로 반환
    except Exception as e:
        return f"예측 중 오류 발생: {str(e)}"