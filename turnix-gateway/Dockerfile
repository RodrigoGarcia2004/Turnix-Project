# ====== Etapa 1: build con Maven ======
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build

# Cachea las dependencias antes de copiar el codigo fuente
COPY pom.xml .
RUN mvn -B -q dependency:go-offline

# Compila el JAR
COPY src ./src
RUN mvn -B -q clean package -DskipTests

# ====== Etapa 2: runtime ligero ======
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

# Usuario no-root por buenas practicas
RUN addgroup -S turnix && adduser -S turnix -G turnix
USER turnix

COPY --from=build /build/target/turnix-gateway.jar app.jar

# JVM tuned para entornos con 512 MB (free tier)
ENV JAVA_OPTS="-XX:+UseContainerSupport -XX:MaxRAMPercentage=70 -XX:+UseG1GC"

EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar app.jar"]
