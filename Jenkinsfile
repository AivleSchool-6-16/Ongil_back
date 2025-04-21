pipeline {
    agent any
    environment {
        // 앱 실행 환경 지정
        APP_ENV       = "development"
        DATABASE_URL  = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"
    }
    stages {
        stage('Checkout') {
            steps {
                // Git에서 코드 체크아웃
                checkout scm
            }
        }
        stage('Build & Test') {
            agent {
                docker {
                    image 'python:3.11-slim'
                    args  '--user root'
                }
            }
            environment {
                // 가상환경 경로
                VIRTUAL_ENV = "${WORKSPACE}/venv"
                // SECRET_KEY Credential
                SECRET_KEY  = credentials('SECRET-KEY')
            }
            steps {
                sh '''
                    echo "Loaded SECRET_KEY: $SECRET_KEY"

                    echo "=== 시스템 패키지 설치 ==="
                    apt-get update && apt-get install -y python3-venv python3-pip libmagic1 libmagic-dev

                    echo "=== 빌드: Python 가상환경 생성 및 의존성 설치 ==="
                    python3 -m venv ${VIRTUAL_ENV}
                    . ${VIRTUAL_ENV}/bin/activate
                    pip install --upgrade pip
                    pip install -r requirements.txt

                    echo "=== 테스트: pytest 실행 ==="
                    pytest --maxfail=1 --disable-warnings -q
                '''
            }
        }
        stage('Deploy to EC2') {
            steps {
                sshagent(['ec2-ssh-key-id']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=no ubuntu@13.209.75.223'\\
                            cd ~/Ongil_back && \\
                            git pull origin main && \\
                            docker build -t ongil-backend:latest . && \\
                            docker stop ongil-back || true && \\
                            docker rm ongil-back || true && \\
                            docker run -d --name ongil-back -p 8000:8000 --env-file .env --restart on-failure ongil-backend:latest'
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
