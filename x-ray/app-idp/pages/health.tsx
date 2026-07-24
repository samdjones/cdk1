import type { GetServerSideProps } from "next";

// Responds at /idp/health (basePath is prepended automatically). Used as
// both the ALB target group health check and the frontend's pre-flight
// side-call, so it short-circuits with a raw JSON response instead of
// rendering a page.
export const getServerSideProps: GetServerSideProps = async ({ res }) => {
  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ status: "ok", service: "xray-idp" }));
  return { props: {} };
};

export default function Health() {
  return null;
}
