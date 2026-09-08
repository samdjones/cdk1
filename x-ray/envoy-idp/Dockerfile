# syntax=docker/dockerfile:1

FROM docker.io/envoyproxy/envoy-distroless:v1.31-latest

COPY envoy.yaml /etc/envoy/envoy.yaml

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/envoy"]
CMD ["-c", "/etc/envoy/envoy.yaml"]
