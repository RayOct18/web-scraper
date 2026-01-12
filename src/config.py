from dataclasses import dataclass, field


@dataclass
class Config:
    seed_urls: list[str] = field(
        default_factory=lambda: [
            "https://go.dev/",
            "https://pkg.go.dev/",
            "https://docs.python.org/",
            "https://docs.github.com/",
            "https://nodejs.org/docs/",
            "https://developer.mozilla.org/",
            "https://docs.docker.com/",
            "https://kubernetes.io/docs/",
            "https://www.rust-lang.org/",
            "https://docs.rs/",
            "https://docs.oracle.com/",
            "https://docs.aws.amazon.com/",
            "https://cloud.google.com/docs/",
            "https://learn.microsoft.com/",
            "https://wiki.archlinux.org/",
            "https://wiki.debian.org/",
            "https://docs.fedoraproject.org/",
            "https://doc.rust-lang.org/",
            "https://ruby-doc.org/",
            "https://docs.julialang.org/",
            "https://github.com/",
            "https://gitlab.com/",
            "https://bitbucket.org/",
            "https://sourceforge.net/",
            "https://codeberg.org/",
            "https://news.ycombinator.com/",
            "https://lobste.rs/",
            "https://slashdot.org/",
            "https://arstechnica.com/",
            "https://techcrunch.com/",
            "https://en.wikipedia.org/",
            "https://en.wikibooks.org/",
            "https://www.britannica.com/",
            "https://arxiv.org/",
            "https://www.nature.com/",
            "https://www.sciencedirect.com/",
            "https://stackoverflow.com/",
            "https://www.w3schools.com/",
            "https://www.tutorialspoint.com/",
            "https://www.geeksforgeeks.org/",
            "https://realpython.com/",
            "https://www.freecodecamp.org/",
            "https://css-tricks.com/",
            "https://smashingmagazine.com/",
            "https://dev.to/",
            "https://hashnode.com/",
            "https://dzone.com/",
            "https://infoq.com/",
            "https://martinfowler.com/",
        ]
    )
    num_workers: int = 20
    max_per_host: int = 10
    max_pages: int = 30000
    request_timeout: float = 10.0
    metrics_port: int = 9090

    # 模擬模式設定
    simulation_mode: bool = False
    simulation_delay_ms: int = 50
    simulation_links_min: int = 5
    simulation_links_max: int = 20
    url_pool_file: str = "url_pool.json"

    # 優化選項
    use_bloom_filter: bool = False
    use_dns_cache: bool = False
