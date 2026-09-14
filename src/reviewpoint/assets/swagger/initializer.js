/* global SwaggerUIBundle */
SwaggerUIBundle({
  url: "/openapi.json",
  dom_id: "#swagger-ui",
  presets: [SwaggerUIBundle.presets.apis],
  layout: "BaseLayout",
  validatorUrl: null,
  persistAuthorization: false,
  queryConfigEnabled: false,
});
