package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.PolicyExecutionControlEntity;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface PolicyExecutionControlRepository
        extends JpaRepository<PolicyExecutionControlEntity, String> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT c FROM PolicyExecutionControlEntity c WHERE c.id = :id")
    Optional<PolicyExecutionControlEntity> findByIdForUpdate(
        @Param("id") String id
    );
}
