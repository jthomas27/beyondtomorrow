FROM nginx:alpine

# Copy nginx config template
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Copy website files
COPY index.html /usr/share/nginx/html/
COPY styles.css /usr/share/nginx/html/

# Set default PORT if not provided
ENV PORT=8080

CMD ["sh", "-c", "envsubst '$PORT' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
