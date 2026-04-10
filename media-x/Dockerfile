# Этап сборки
FROM golang:1.24-bullseye AS builder

WORKDIR /app

# Кэшируем зависимости
COPY go.mod go.sum ./
RUN go mod download

# Копируем исходный код
COPY . .

# Собираем оптимизированный бинарник
RUN CGO_ENABLED=0 GOOS=linux go build -p 1 -ldflags="-s -w" -o media-x main.go

# Финальный образ
FROM debian:bullseye-slim

WORKDIR /app

# Устанавливаем сертификаты (нужны для HTTPS запросов к сайтам)
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/media-x .

EXPOSE 8080

CMD ["./media-x"]
