"use strict";

// Starts the ADOT auto-instrumentation (same as requiring
// "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register" directly),
// then patches the HTTP client instrumentation so the ECS task-credentials
// call (http://169.254.170.2/v2/credentials/...) gets a readable name in the
// X-Ray service map instead of showing up as the raw link-local IP. That
// call happens on every AWS SDK request (it's the SDK fetching temporary
// task-role credentials) and has nothing to do with application logic.
const { instrumentations } = require("@aws/aws-distro-opentelemetry-node-autoinstrumentation/register");

const ECS_CREDENTIALS_HOST = "169.254.170.2";

const httpInstrumentation = instrumentations.find(
  (instrumentation) => instrumentation.instrumentationName === "@opentelemetry/instrumentation-http",
);

if (httpInstrumentation) {
  httpInstrumentation.setConfig({
    ...httpInstrumentation.getConfig(),
    requestHook: (span, request) => {
      const host = typeof request.getHeader === "function" ? request.getHeader("host") : undefined;
      if (typeof host === "string" && host.split(":")[0] === ECS_CREDENTIALS_HOST) {
        span.updateName("ECS Task Credentials");
        // peer.service is what the AWS X-Ray OTel exporter uses to label a
        // remote node when it isn't recognized as a named AWS API call.
        span.setAttribute("peer.service", "ecs-task-credentials");
      }
    },
  });
}
