<footer class="footer-wrapper">
	<div class="gradient-line"></div>
	<div class="footer-content">
		<div class="flex items-center gap-2 mb-3">
			<img src="/lastword.svg" alt="LASTWORD" height="26" width="26" />
			<span class="text-base font-semibold">LASTWORD <span class="gradient-text">Explorer</span></span>
		</div>
		<p class="footer-desc">
			The agent proposes. The badge has the last word. Every supplier payment is traced here, end to end:
			proposed by the AI agent, attested and approved on a TROPIC01 hardware badge over LoRa, paid by the contract.
		</p>
		<div class="footer-bottom">
			<span class="copyright">LASTWORD · Secure Horizons hackathon {new Date().getFullYear()}</span>
			<span class="separator">|</span>
			<span>Avalanche L1 · synthetic demo data only</span>
		</div>
	</div>
</footer>

<style lang="postcss">
	@reference "$lib/../app.css";
	.footer-wrapper {
		@apply mt-auto w-full;
	}
	.gradient-line {
		height: 1px;
		background: linear-gradient(90deg, transparent, rgba(255, 90, 31, 0.4), rgba(255, 138, 76, 0.3), transparent);
	}
	.footer-content {
		@apply flex flex-col items-center py-8 px-4 text-sm;
		background: rgba(243, 242, 238, 0.6);
		backdrop-filter: blur(8px);
	}
	.footer-desc {
		color: rgba(28, 27, 24, 0.5);
		@apply mb-5 max-w-md text-center text-sm;
	}
	.social-links {
		@apply flex items-center gap-3 mb-5;
	}
	.social-icon {
		@apply flex items-center justify-center rounded-lg p-2.5;
		background: rgba(28, 27, 24, 0.06);
		border: 1px solid rgba(28, 27, 24, 0.09);
		color: rgba(28, 27, 24, 0.75);
		transition: all 0.2s ease;
		&:hover {
			color: #ff5a1f;
			background: rgba(255, 90, 31, 0.08);
			border-color: rgba(255, 90, 31, 0.2);
		}
	}
	.footer-bottom {
		@apply flex items-center gap-2 flex-wrap justify-center;
		color: rgba(28, 27, 24, 0.37);
	}
	.separator {
		color: rgba(28, 27, 24, 0.18);
	}
	.powered-by {
		transition: color 0.2s ease;
		&:hover {
			color: rgba(28, 27, 24, 0.75);
		}
	}
</style>
