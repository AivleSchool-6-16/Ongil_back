pipeline {
  agent any

  environment {
    APP_ENV       = 'development'
    DATABASE_URL  = 'mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb'
    DOCKER_IMAGE  = 'ejji/ongil-backend:latest'
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Build & Push Docker Image') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'dockerhub-id', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
          sh '''
            echo "✅ Docker 이미지 빌드 및 푸시"
            docker build -t $DOCKER_IMAGE .
            echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
            docker push $DOCKER_IMAGE
          '''
        }
      }
    }

    stage('Deploy to EC2 via SSH') {
    steps {
        sshagent(credentials: ['ec2-ssh-key-id']) {
        sh '''
            echo "🚀 EC2에 SSH로 접속 후 배포 시작"
            ssh -o StrictHostKeyChecking=no ubuntu@3.35.24.187 bash -s <<'EOF'
    echo "[INFO] EC2 접속 성공"
    cd ~/Ongil_project
    docker compose pull backend
    docker compose up -d backend
    echo "[✅] 배포 완료"
    EOF
        '''
        }
    }
    }

  post {
    success {
      echo '✅ 백엔드 파이프라인 완료!'
    }
    failure {
      echo '❌ 파이프라인 실패. 로그 확인 요망.'
    }
  }
}