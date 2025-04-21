pipeline {
    agent any
    environment {
        // Workspace 내의 가상환경 경로
        VIRTUAL_ENV = "${WORKSPACE}/venv"
        PYTHONPATH = "${WORKSPACE}"
        // 앱 실행 환경 지정 (development, staging, production 등)
        APP_ENV = "development"
        // DB 접속 정보
        DATABASE_URL = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"
    }
    stages {
        stage('Prepare Workspace') { 
            steps {
                // 마운트된 /mnt/ongil-backend 에서 현재 Workspace로 파일 복사(숨김 파일 포함)
                sh 'cp -r /mnt/ongil-backend/* .'
            }
        }
        stage('Build') {
            steps {
                // withCredentials를 사용하여 SECRET_KEY 환경 변수를 주입
                withCredentials([string(credentialsId: 'SECRET-KEY', variable: 'SECRET_KEY')]) {
                    sh '''
                    echo "=== Python 설치 시작 ==="
                    apt-get update
                    apt-get install -y python3 python3-venv python3-pip libmagic1 libmagic-dev

                    echo "Loaded SECRET_KEY: $SECRET_KEY"
                    
                    echo "=== 빌드 단계 시작: Python 가상환경 생성 및 패키지 설치 ==="
                    python3 -m venv ${VIRTUAL_ENV}
                    . ${VIRTUAL_ENV}/bin/activate
                    pip install --upgrade pip
                    pip install -r requirements.txt
                    '''
                }
            }
        }
        stage('Test') {
            steps {
                // TEST 단계에서도 동일하게 withCredentials 블록을 사용
                withCredentials([string(credentialsId: 'SECRET-KEY', variable: 'SECRET_KEY')]) {
                    sh '''
                    echo "=== 테스트 단계 시작: pytest 실행 ==="
                    . ${VIRTUAL_ENV}/bin/activate
                    pytest --maxfail=1 --disable-warnings -q
                    '''
                }
            }
        }
        stage('Deploy to EC2') {
            steps {
                sshagent(['ec2-ssh-key-id']) {
                sh """
                    ssh -o StrictHostKeyChecking=no ubuntu@13.209.75.223'
                    cd ~/Ongil_back
                    git pull origin main
                    docker build -t ongil-backend:latest .
                    docker stop ongil-back || true
                    docker rm ongil-back || true
                    docker run -d --name ongil-back -p 8000:8000 --env-file .env --restart on-failure ongil-backend:latest
                    '
                """
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
