from dataclasses import dataclass, field


@dataclass
class EvalResult:
    score: float
    reasoning: str
    criteria: str
    threshold: float = field(default=0.7)

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold
