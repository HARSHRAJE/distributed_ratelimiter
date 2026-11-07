FROM gradle:9.8.2-jdk21-alpine AS build
WORKDIR /workspace
COPY build.gradle settings.gradle ./
COPY src ./src
RUN gradle bootJar --no-daemon \
    && for jar in build/libs/*.jar; do \
        case "$jar" in *-plain.jar) ;; *) cp "$jar" /workspace/app.jar ;; esac; \
    done

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S app && adduser -S -G app app
COPY --from=build --chown=app:app /workspace/app.jar /app/app.jar
USER app
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
