package ghostbusters

import rego.v1

policy_version := "1.0"

remediation_action if input.recommendation.action == "downsize"
remediation_action if input.recommendation.action == "schedule"

safe_outcome if input.recommendation.action == "keep"
safe_outcome if input.recommendation.action == "abstain"
safe_outcome if input.recommendation.action == "request_evidence"

deny contains violation if {
    lower(input.resource.environment) == "production"
    not safe_outcome
    violation := {
        "msg": "Production resources cannot be automatically remediated",
        "metadata": {
            "code": "PRODUCTION_REMEDIATION_BLOCKED",
            "severity": "critical",
        },
    }
}

deny contains violation if {
    input.resource.destructive
    not safe_outcome
    violation := {
        "msg": "Unexpected delete or destructive Terraform operations are blocked",
        "metadata": {
            "code": "DESTRUCTIVE_ACTION_BLOCKED",
            "severity": "critical",
        },
    }
}

deny contains violation if {
    remediation_action
    input.resource.ownership_status != "known"
    violation := {
        "msg": "Resource ownership is unknown; remediation is blocked",
        "metadata": {
            "code": "UNKNOWN_OWNERSHIP",
            "severity": "critical",
        },
    }
}

deny contains violation if {
    input.resource.active_dependencies
    input.recommendation.action in {"downsize", "schedule", "abstain"}
    violation := {
        "msg": "Critical active dependencies prevent remediation",
        "metadata": {
            "code": "ACTIVE_DEPENDENCY",
            "severity": "critical",
        },
    }
}

deny contains violation if {
    remediation_action
    count(input.evidence.missing_critical) > 0
    violation := {
        "msg": "Critical evidence is missing; remediation is blocked",
        "metadata": {
            "code": "MISSING_CRITICAL_EVIDENCE",
            "severity": "critical",
        },
    }
}

deny contains violation if {
    remediation_action
    some finding in input.verifier_failures
    finding.severity == "critical"
    violation := {
        "msg": "A critical verifier failure prevents remediation",
        "metadata": {
            "code": "CRITICAL_VERIFIER_FAILURE",
            "severity": "critical",
        },
    }
}

deny contains violation if {
    remediation_action
    input.confidence.score < input.confidence.minimum_threshold
    violation := {
        "msg": sprintf(
            "Confidence %.2f is below the required threshold %.2f",
            [input.confidence.score, input.confidence.minimum_threshold],
        ),
        "metadata": {
            "code": "LOW_CONFIDENCE",
            "severity": "critical",
        },
    }
}

warn contains warning if {
    remediation_action
    warning := "Human approval is mandatory before any remediation action"
}
