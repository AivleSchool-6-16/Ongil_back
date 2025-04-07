pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                git branch: 'main', url: 'https://github.com/AivleSchool-6-16/Ongil_back.git'
            }
        }
        stage('Build Image') {
            steps {
                sh 'docker build -t ongil-backend:latest .'
            }
        }
        stage('Test') {
            steps {
                sh '''
                docker run -d --name test-ongil ongil-backend:latest
                docker exec test-ongil pytest
                docker stop test-ongil
                docker rm test-ongil
                '''
            }
        }
        stage('Push to Registry') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-credentials', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                    sh '''
                    docker login -u $DOCKER_USER -p $DOCKER_PASS
                    docker tag ongil-backend:latest ejji/ongil-backend:latest
                    docker push ejji/ongil-backend:latest
                    '''
                }
            }
        }
        stage('Deploy') {
            steps {
                sshagent(['ec2-ssh-credentials']) {
                    sh '''
                    ssh -o StrictHostKeyChecking=no ec2-user@13.125.225.237 '
                      docker pull ejji/ongil-backend:latest &&
                      docker stop ongil-backend || true &&
                      docker rm ongil-backend || true &&
                      docker run -d --name ongil-backend -p 8000:8000 ejji/ongil-backend:latest
                    '
                    '''
                }
            }
        }
    }
    
    post {
        failure {
            echo '빌드 실패! 로그를 확인하세요.'
        }
    }
}