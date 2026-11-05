package com.ratelimiter.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties =
	"security.jwt.public-key-location=classpath:keys/test-auth-public.pem")
class GatewayApplicationTests {

	@Test
	void contextLoads() {
	}

}
