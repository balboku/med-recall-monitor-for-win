FROM node:20 AS base
WORKDIR /app
COPY package*.json ./
RUN npm install

# 開發階段 (Dev Stage) - 用於熱重載
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# 編譯階段 (Builder Stage) - 用於生產部署
FROM base AS builder
COPY . .
RUN npm run build

# 生產運行階段 (Production Stage)
FROM nginx:alpine AS production
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
