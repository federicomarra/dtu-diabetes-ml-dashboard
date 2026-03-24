pipeline {
    agent any

    environment {
        DATABASE_URL = credentials('diabetes-db-url')
    }

    stages {
        stage('Backend: Install') {
            steps {
                dir('backend') {
                    sh 'pip install -r requirements.txt'
                    sh 'pip install pytest'
                }
            }
        }

        stage('Backend: Test') {
            steps {
                dir('backend') {
                    sh 'python -m pytest tests/ -v'
                }
            }
        }

        stage('Backend: DB Migrations') {
            steps {
                dir('backend') {
                    sh 'flask db upgrade'
                }
            }
        }

        stage('Frontend: Install') {
            steps {
                dir('frontend') {
                    sh 'npm ci'
                }
            }
        }

        stage('Frontend: Lint') {
            steps {
                dir('frontend') {
                    sh 'npm run lint'
                }
            }
        }

        stage('Frontend: Build') {
            steps {
                dir('frontend') {
                    sh 'npm run build'
                }
            }
        }
    }

    post {
        failure {
            echo 'Pipeline failed — check logs above.'
        }
        success {
            echo 'All stages passed.'
        }
    }
}