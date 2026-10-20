// Main JavaScript for Gym Management System

document.addEventListener('DOMContentLoaded', function() {

    // ==================== Back to Top Button ====================
    const backToTopButton = document.createElement('div');
    backToTopButton.className = 'back-to-top';
    backToTopButton.innerHTML = '<i class="bi bi-arrow-up"></i>';
    document.body.appendChild(backToTopButton);

    // Show/hide back to top button
    window.addEventListener('scroll', function() {
        if (window.pageYOffset > 300) {
            backToTopButton.classList.add('show');
        } else {
            backToTopButton.classList.remove('show');
        }
    });

    // Scroll to top when clicked
    backToTopButton.addEventListener('click', function() {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });

    // ==================== Form Validation ====================
    const forms = document.querySelectorAll('.needs-validation');

    Array.from(forms).forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    });

    // ==================== Auto-dismiss Alerts ====================
    const alerts = document.querySelectorAll('.alert');

    alerts.forEach(function(alert) {
        if (!alert.classList.contains('alert-permanent')) {
            setTimeout(function() {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }, 5000); // Auto-dismiss after 5 seconds
        }
    });

    // ==================== Smooth Scroll for Anchor Links ====================
    const anchorLinks = document.querySelectorAll('a[href^="#"]');

    anchorLinks.forEach(function(link) {
        link.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            if (targetId !== '#' && document.querySelector(targetId)) {
                e.preventDefault();
                const targetElement = document.querySelector(targetId);
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // ==================== Navbar Active State ====================
    const currentLocation = window.location.pathname;
    const navLinks = document.querySelectorAll('.navbar-nav .nav-link');

    navLinks.forEach(function(link) {
        if (link.getAttribute('href') === currentLocation) {
            link.classList.add('active');
        }
    });

    // ==================== Loading Button State ====================
    const loadingButtons = document.querySelectorAll('.btn-loading');

    loadingButtons.forEach(function(button) {
        button.addEventListener('click', function() {
            const originalText = this.innerHTML;
            this.disabled = true;
            this.innerHTML = '<span class="loading"></span> در حال پردازش...';

            // Re-enable after form submission or API call
            setTimeout(function() {
                button.disabled = false;
                button.innerHTML = originalText;
            }, 3000);
        });
    });

    // ==================== Card Animations on Scroll ====================
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '0';
                entry.target.style.transform = 'translateY(30px)';

                setTimeout(function() {
                    entry.target.style.transition = 'all 0.6s ease';
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                }, 100);

                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    // Observe all cards
    const cards = document.querySelectorAll('.card');
    cards.forEach(function(card) {
        observer.observe(card);
    });

    // ==================== Phone Number Formatting ====================
    const phoneInputs = document.querySelectorAll('input[type="tel"]');

    phoneInputs.forEach(function(input) {
        input.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, ''); // Remove non-digits

            // Format: 0912-345-6789
            if (value.length > 4 && value.length <= 7) {
                value = value.slice(0, 4) + '-' + value.slice(4);
            } else if (value.length > 7) {
                value = value.slice(0, 4) + '-' + value.slice(4, 7) + '-' + value.slice(7, 11);
            }

            e.target.value = value;
        });
    });

    // ==================== Image Preview ====================
    const imageInputs = document.querySelectorAll('input[type="file"][accept*="image"]');

    imageInputs.forEach(function(input) {
        input.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(event) {
                    const previewId = input.getAttribute('data-preview');
                    if (previewId) {
                        const previewElement = document.getElementById(previewId);
                        if (previewElement) {
                            previewElement.src = event.target.result;
                            previewElement.style.display = 'block';
                        }
                    }
                };
                reader.readAsDataURL(file);
            }
        });
    });

    // ==================== Copy to Clipboard ====================
    const copyButtons = document.querySelectorAll('[data-copy]');

    copyButtons.forEach(function(button) {
        button.addEventListener('click', function() {
            const textToCopy = this.getAttribute('data-copy');

            navigator.clipboard.writeText(textToCopy).then(function() {
                // Show success message
                const originalText = button.innerHTML;
                button.innerHTML = '<i class="bi bi-check"></i> کپی شد';
                button.classList.add('btn-success');

                setTimeout(function() {
                    button.innerHTML = originalText;
                    button.classList.remove('btn-success');
                }, 2000);
            }).catch(function(err) {
                console.error('خطا در کپی کردن:', err);
            });
        });
    });

    // ==================== Tooltip Initialization ====================
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // ==================== Popover Initialization ====================
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function(popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });

    // ==================== Character Counter for Textareas ====================
    const textareas = document.querySelectorAll('textarea[maxlength]');

    textareas.forEach(function(textarea) {
        const maxLength = textarea.getAttribute('maxlength');
        const counter = document.createElement('div');
        counter.className = 'form-text text-end';
        counter.innerHTML = `<span class="current">0</span> / ${maxLength}`;
        textarea.parentElement.appendChild(counter);

        textarea.addEventListener('input', function() {
            const currentLength = this.value.length;
            counter.querySelector('.current').textContent = currentLength;

            if (currentLength >= maxLength * 0.9) {
                counter.classList.add('text-warning');
            } else {
                counter.classList.remove('text-warning');
            }
        });
    });

    // ==================== Confirm Before Delete ====================
    const deleteButtons = document.querySelectorAll('[data-confirm-delete]');

    deleteButtons.forEach(function(button) {
        button.addEventListener('click', function(e) {
            const message = this.getAttribute('data-confirm-delete') || 'آیا مطمئن هستید که می‌خواهید این مورد را حذف کنید؟';

            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // ==================== Auto-resize Textarea ====================
    const autoResizeTextareas = document.querySelectorAll('.auto-resize');

    autoResizeTextareas.forEach(function(textarea) {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = this.scrollHeight + 'px';
        });
    });

    // ==================== Number Input Validation ====================
    const numberInputs = document.querySelectorAll('input[type="number"]');

    numberInputs.forEach(function(input) {
        input.addEventListener('keypress', function(e) {
            // Allow only numbers and specific keys
            if (!/[\d.]/.test(e.key) && !['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'Tab'].includes(e.key)) {
                e.preventDefault();
            }
        });
    });

    // ==================== Dynamic Search/Filter ====================
    const searchInputs = document.querySelectorAll('[data-search-target]');

    searchInputs.forEach(function(input) {
        input.addEventListener('input', function() {
            const searchTerm = this.value.toLowerCase();
            const targetSelector = this.getAttribute('data-search-target');
            const targets = document.querySelectorAll(targetSelector);

            targets.forEach(function(target) {
                const text = target.textContent.toLowerCase();
                if (text.includes(searchTerm)) {
                    target.style.display = '';
                } else {
                    target.style.display = 'none';
                }
            });
        });
    });

    console.log('Gym Management System initialized successfully!');
});
