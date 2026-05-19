FROM node:20-alpine AS base
WORKDIR /app
COPY . .
RUN yarn install --frozen-lockfile || yarn install
WORKDIR /app/frontend
EXPOSE 3000
CMD ["yarn", "dev"]
