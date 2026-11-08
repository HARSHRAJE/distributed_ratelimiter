package com.ratelimiter.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties =
	"security.jwt.public-key-location=classpath:keys/test-auth-public.pem")
class GatewayApplicationTests {

	@Autowired
	private RouteLocator routeLocator;

	@Test
	void contextLoads() {
	}

	@Test
	void routesAiControllerThroughGateway() {
		assertThat(routeLocator.getRoutes()
			.map(Route::getId)
			.collectList()
			.block())
			.contains("ai-controller-api");
	}

}
