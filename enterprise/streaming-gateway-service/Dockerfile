FROM eclipse-temurin:21-jre
WORKDIR /app
COPY target/streaming-gateway-service-2.0.0.jar app.jar
EXPOSE 8081
ENTRYPOINT ["java","-jar","app.jar"]
