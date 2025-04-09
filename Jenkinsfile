pipeline {
    agent any
    environment {
        // Jenkins 작업 디렉토리 내의 가상환경 경로
        VIRTUAL_ENV = "${WORKSPACE}/venv"
        // 앱 실행 환경 지정 (development, staging, production 등)
        APP_ENV = "development"
        // DB 접속 
        DATABASE_URL = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"
    }
    stages {
        stage('Checkout') {
            steps {
                // local workspace
                sh 'cp -r "/c/Users/jej/OneDrive/바탕 화면/AIVLE/big_proj/ongil-backend/"* .'
            }
        }
        stage('Build') {
            steps {
                script {
                    // Python 가상환경 생성 및 라이브러리 설치
                    sh '''
                    echo "=== 빌드 단계 시작: Python 가상환경 생성 및 패키지 설치 ==="
                    python -m venv ${VIRTUAL_ENV}
                    . ${VIRTUAL_ENV}/bin/activate
                    pip install --upgrade pip
                    pip install -r requirements.txt
                    '''
                }
            }
        }
        stage('Test') {
            steps {
                script {
                    // pytest를 사용한 유닛/통합 테스트 실행
                    sh '''
                    echo "=== 테스트 단계 시작: pytest 실행 ==="
                    . ${VIRTUAL_ENV}/bin/activate
                    pytest --maxfail=1 --disable-warnings -q
                    '''
                }
            }
        }
    }
    post {
        success {
            echo '빌드 및 테스트가 성공적으로 완료되었습니다.'
        }
        failure {
            echo '빌드 또는 테스트 중 오류가 발생했습니다.'
        }
    }
}