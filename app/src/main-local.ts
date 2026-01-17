import app from "./app.js";
import { setLambdaService, LambdaService } from "./services/lambdaService.js";

// Mock Lambda service that performs the multiplication locally
const mockLambdaService: LambdaService = {
  async invokeMultiply({ a, b }) {
    console.log(`[Mock Lambda] Multiplying ${a} * ${b}`);
    return { result: a * b };
  },
};

setLambdaService(mockLambdaService);

const PORT = process.env.PORT || 8000;

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT} (with mock Lambda)`);
});
